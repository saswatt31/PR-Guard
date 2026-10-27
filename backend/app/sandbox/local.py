"""Host-process sandbox used only for local development and demo recording.

This backend does **not** provide a security boundary: it cannot disable networking,
enforce a read-only root filesystem, or prevent a malicious repository from reading
files owned by the host user. ``SANDBOX_MODE=local`` is therefore opt-in and clearly
labelled in the dashboard/README. Docker is the only supported isolation boundary.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

from app.sandbox.errors import SandboxPolicyError
from app.sandbox.models import SandboxPhase, SandboxResult, SandboxStatus
from app.sandbox.security import (
    local_environment,
    truncate_log,
    validate_command,
    validate_executable,
    validate_workspace,
)
from app.settings import Settings

MAX_LOCAL_LOG_CHARS = 120_000


class LocalSandboxRunner:
    isolation = "local (NOT a security boundary)"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def available(self) -> tuple[bool, str]:
        return (shutil.which("node") is not None, "node is not installed")

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
        del labels  # Docker labels have no local equivalent.
        argv = validate_command(tuple(command))
        validate_executable(argv)
        workspace = validate_workspace(workspace)
        try:
            normalized_phase = SandboxPhase(phase).value
        except ValueError as exc:
            raise SandboxPolicyError(f"unknown sandbox phase: {phase}") from exc

        if timeout_seconds is None:
            timeout_seconds = (
                self.settings.sandbox_timeout_seconds
                if normalized_phase == SandboxPhase.TEST
                else self.settings.sandbox_install_timeout_seconds
            )
        if timeout_seconds < 1:
            raise SandboxPolicyError("sandbox timeout must be positive")

        executable = shutil.which(argv[0])
        if executable is None:
            raise SandboxPolicyError(f"local executable not found: {argv[0]}")

        started = time.monotonic()
        process = subprocess.Popen(
            [executable, *argv[1:]],
            cwd=workspace,
            env=local_environment(env),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            start_new_session=os.name != "nt",
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )
        timed_out = False
        try:
            stdout, stderr = process.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_process_tree(process)
            stdout, stderr = process.communicate()
        duration_ms = int((time.monotonic() - started) * 1000)

        if timed_out:
            status = SandboxStatus.TIMEOUT
            error = f"process exceeded the {timeout_seconds}s timeout and was killed"
        elif process.returncode == 0:
            status = SandboxStatus.PASSED
            error = None
        else:
            status = SandboxStatus.FAILED
            error = None

        return SandboxResult(
            phase=normalized_phase,
            command=argv,
            status=status,
            exit_code=process.returncode,
            timed_out=timed_out,
            duration_ms=duration_ms,
            stdout=truncate_log(stdout or "", MAX_LOCAL_LOG_CHARS),
            stderr=truncate_log(stderr or "", MAX_LOCAL_LOG_CHARS),
            # Local mode cannot enforce network isolation; report the truth.
            network_disabled=False,
            isolation=self.isolation,
            error=error,
        )


def _kill_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":  # pragma: no cover - exercised on Windows only
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return
    try:  # pragma: no cover - POSIX-only
        os.killpg(process.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        process.kill()
