"""Docker-backed sandbox runner.

Security controls are applied at container creation: non-root user, read-only root
filesystem, no capabilities, no-new-privileges, memory/CPU/PID limits, a tmpfs for
temporary files, and ``network_disabled=True`` for the test phase. The repository
workspace is the only writable bind mount, and all containers are force-removed after
each run.
"""

from __future__ import annotations

import contextlib
import os
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import docker
import requests
from docker.errors import DockerException, ImageNotFound

from app.sandbox.errors import SandboxPolicyError, SandboxUnavailable
from app.sandbox.models import SandboxLimits, SandboxPhase, SandboxResult, SandboxStatus
from app.sandbox.security import (
    docker_environment,
    truncate_log,
    validate_command,
    validate_executable,
    validate_workspace,
)
from app.settings import Settings

SANDBOX_USER = "10001:10001"
SHM_SIZE = "64m"


class DockerSandboxRunner:
    isolation = "docker"

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self.settings = settings
        self._client = client
        self._client_error: str | None = None

    @property
    def client(self) -> Any:
        if self._client is not None:
            return self._client
        if self._client_error is not None:
            raise SandboxUnavailable(self._client_error)
        try:
            self._client = docker.from_env()
        except DockerException as exc:  # pragma: no cover - depends on host daemon
            self._client_error = f"Docker daemon is unavailable: {exc}"
            raise SandboxUnavailable(self._client_error) from exc
        return self._client

    def available(self) -> tuple[bool, str]:
        try:
            self.client.ping()
        except (SandboxUnavailable, DockerException, requests.RequestException) as exc:
            return False, str(exc)
        return True, ""

    def ensure_image(self) -> None:
        """Fetch the pinned sandbox image if it is not present locally."""

        try:
            self.client.images.get(self.settings.sandbox_image)
        except ImageNotFound:
            self.client.images.pull(self.settings.sandbox_image)

    def run(
        self,
        workspace: Path,
        command: Sequence[str],
        *,
        phase: str = SandboxPhase.TEST,
        network_disabled: bool = True,
        timeout_seconds: int | None = None,
        env: Mapping[str, str] | None = None,
        labels: Mapping[str, str] | None = None,
    ) -> SandboxResult:
        argv = validate_command(tuple(command))
        validate_executable(argv)
        workspace = validate_workspace(workspace)
        try:
            normalized_phase = SandboxPhase(phase).value
        except ValueError as exc:
            raise SandboxPolicyError(f"unknown sandbox phase: {phase}") from exc

        if normalized_phase == SandboxPhase.TEST and not network_disabled:
            raise SandboxPolicyError("the test phase must run with the network disabled")

        if timeout_seconds is None:
            timeout_seconds = (
                self.settings.sandbox_timeout_seconds
                if normalized_phase == SandboxPhase.TEST
                else self.settings.sandbox_install_timeout_seconds
            )
        if timeout_seconds < 1:
            raise SandboxPolicyError("sandbox timeout must be positive")

        limits = SandboxLimits(
            timeout_seconds=timeout_seconds,
            memory_mb=self.settings.sandbox_memory_mb,
            cpus=self.settings.sandbox_cpus,
            pids_limit=self.settings.sandbox_pids_limit,
        )
        environment = docker_environment(env)
        container = None
        started = time.monotonic()

        try:
            _make_workspace_writable(workspace)
            container = self.client.containers.create(
                image=self.settings.sandbox_image,
                command=list(argv),
                working_dir="/workspace",
                volumes={str(workspace): {"bind": "/workspace", "mode": "rw"}},
                environment=environment,
                user=SANDBOX_USER,
                network_disabled=network_disabled,
                read_only=True,
                mem_limit=f"{limits.memory_mb}m",
                nano_cpus=int(limits.cpus * 1_000_000_000),
                pids_limit=limits.pids_limit,
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
                tmpfs={"/tmp": "rw,noexec,nosuid,size=256m"},
                shm_size=SHM_SIZE,
                init=True,
                labels={**dict(labels or {}), "prguard.sandbox": "true"},
            )
            container.start()
            exit_code, timed_out, wait_error = _wait_for_exit(container, timeout_seconds)
            stdout = _decode_logs(container, stdout=True, stderr=False)
            stderr = _decode_logs(container, stdout=False, stderr=True)
            status = _status_for(exit_code, timed_out, wait_error)
            return SandboxResult(
                phase=normalized_phase,
                command=argv,
                status=status,
                exit_code=exit_code,
                timed_out=timed_out,
                duration_ms=_elapsed_ms(started),
                stdout=truncate_log(stdout, limits.max_log_chars),
                stderr=truncate_log(stderr, limits.max_log_chars),
                network_disabled=network_disabled,
                isolation=self.isolation,
                error=wait_error,
            )
        except (DockerException, requests.RequestException, OSError) as exc:
            return SandboxResult(
                phase=normalized_phase,
                command=argv,
                status=SandboxStatus.ERROR,
                exit_code=None,
                timed_out=False,
                duration_ms=_elapsed_ms(started),
                stdout="",
                stderr="",
                network_disabled=network_disabled,
                isolation=self.isolation,
                error=f"{type(exc).__name__}: {exc}",
            )
        finally:
            if container is not None:
                _remove_container(container)


def _wait_for_exit(container: Any, timeout_seconds: int) -> tuple[int | None, bool, str | None]:
    try:
        result = container.wait(timeout=timeout_seconds)
    except requests.exceptions.ReadTimeout:
        with contextlib.suppress(DockerException, requests.RequestException, OSError):
            container.kill()
        return None, True, f"container exceeded the {timeout_seconds}s timeout and was killed"
    except (DockerException, requests.RequestException, OSError) as exc:
        return None, False, f"{type(exc).__name__}: {exc}"
    exit_code = result.get("StatusCode") if isinstance(result, dict) else None
    return exit_code, False, None


def _status_for(exit_code: int | None, timed_out: bool, error: str | None) -> str:
    if timed_out:
        return SandboxStatus.TIMEOUT
    if error is not None:
        return SandboxStatus.ERROR
    return SandboxStatus.PASSED if exit_code == 0 else SandboxStatus.FAILED


def _decode_logs(container: Any, *, stdout: bool, stderr: bool) -> str:
    try:
        raw = container.logs(stdout=stdout, stderr=stderr)
    except (DockerException, requests.RequestException, OSError):
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", "replace")
    return str(raw)


def _remove_container(container: Any) -> None:
    with contextlib.suppress(DockerException, requests.RequestException, OSError):
        container.remove(force=True)


def _make_workspace_writable(workspace: Path) -> None:
    """The sandbox user is not the backend user; allow it to write build output."""

    if os.name == "nt":  # pragma: no cover - Docker Desktop maps permissions itself
        return
    with contextlib.suppress(OSError):  # pragma: no cover - surfaces at container start
        workspace.chmod(0o777)


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
