"""Docker runner unit tests use a fake client; real-daemon tests are marked/skipped."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import docker
import pytest
import requests

from app.sandbox.docker import DockerSandboxRunner
from app.sandbox.errors import SandboxPolicyError, SandboxUnavailable
from app.sandbox.factory import build_sandbox
from app.sandbox.local import LocalSandboxRunner, _kill_process_tree
from app.sandbox.models import SandboxCommand, SandboxLimits, SandboxResult
from app.sandbox.security import truncate_log
from app.settings import Settings


class FakeContainer:
    def __init__(
        self,
        *,
        wait_result: dict[str, int] | None = None,
        wait_error: Exception | None = None,
        stdout: bytes | str = b"ok\n",
        stderr: bytes | str = b"",
        logs_error: Exception | None = None,
        remove_error: Exception | None = None,
    ) -> None:
        self.wait_result = wait_result or {"StatusCode": 0}
        self.wait_error = wait_error
        self.stdout = stdout
        self.stderr = stderr
        self.logs_error = logs_error
        self.remove_error = remove_error
        self.started = False
        self.killed = False
        self.removed = False

    def start(self) -> None:
        self.started = True

    def wait(self, timeout: int | None = None) -> dict[str, int]:
        assert timeout is not None
        if self.wait_error is not None:
            raise self.wait_error
        return self.wait_result

    def logs(self, *, stdout: bool, stderr: bool) -> bytes | str:
        if self.logs_error is not None:
            raise self.logs_error
        if stdout:
            return self.stdout
        if stderr:
            return self.stderr
        return b""

    def kill(self) -> None:
        self.killed = True

    def remove(self, force: bool = False) -> None:
        assert force is True
        if self.remove_error is not None:
            raise self.remove_error
        self.removed = True


class FakeContainers:
    def __init__(
        self, container: FakeContainer | None = None, create_error: Exception | None = None
    ):
        self.container = container or FakeContainer()
        self.create_error = create_error
        self.created: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> FakeContainer:
        self.created.append(kwargs)
        if self.create_error is not None:
            raise self.create_error
        return self.container


class FakeImages:
    def __init__(self, *, present: bool = True, pull_error: Exception | None = None) -> None:
        self.present = present
        self.pull_error = pull_error
        self.pulled: list[str] = []

    def get(self, name: str) -> object:
        if not self.present:
            raise docker.errors.ImageNotFound(name)
        return object()

    def pull(self, name: str) -> object:
        if self.pull_error is not None:
            raise self.pull_error
        self.pulled.append(name)
        return object()


class FakeClient:
    def __init__(
        self,
        *,
        container: FakeContainer | None = None,
        create_error: Exception | None = None,
        ping_error: Exception | None = None,
        images: FakeImages | None = None,
    ) -> None:
        self.containers = FakeContainers(container=container, create_error=create_error)
        self.images = images or FakeImages()
        self.ping_error = ping_error

    def ping(self) -> bool:
        if self.ping_error is not None:
            raise self.ping_error
        return True


@pytest.fixture
def docker_settings(settings: Settings) -> Settings:
    return settings.model_copy(update={"sandbox_mode": "docker", "sandbox_image": "test-image"})


def test_run_applies_security_controls_and_removes_container(
    tmp_path: Path, docker_settings: Settings
) -> None:
    container = FakeContainer(stdout=b"stdout\n", stderr=b"stderr\n")
    client = FakeClient(container=container)
    runner = DockerSandboxRunner(docker_settings, client=client)

    result = runner.run(tmp_path, ["node", "-e", "console.log(1)"])

    assert result.status == "passed"
    assert result.passed is True
    assert result.exit_code == 0
    assert result.network_disabled is True
    assert result.isolation == "docker"
    assert result.stdout == "stdout\n"
    assert result.stderr == "stderr\n"
    assert container.started is True
    assert container.removed is True

    [kwargs] = client.containers.created
    assert kwargs["image"] == "test-image"
    assert kwargs["command"] == ["node", "-e", "console.log(1)"]
    assert kwargs["working_dir"] == "/workspace"
    assert kwargs["volumes"] == {str(tmp_path.resolve()): {"bind": "/workspace", "mode": "rw"}}
    assert kwargs["user"] == "10001:10001"
    assert kwargs["read_only"] is True
    assert kwargs["network_disabled"] is True
    assert kwargs["cap_drop"] == ["ALL"]
    assert kwargs["security_opt"] == ["no-new-privileges:true"]
    assert kwargs["mem_limit"] == "1024m"
    assert kwargs["nano_cpus"] == 1_000_000_000
    assert kwargs["pids_limit"] == 256
    assert kwargs["init"] is True
    assert kwargs["tmpfs"] == {"/tmp": "rw,noexec,nosuid,size=256m"}
    assert "GITHUB_TOKEN" not in kwargs["environment"]
    assert kwargs["environment"]["CI"] == "1"


def test_install_phase_may_use_network(tmp_path: Path, docker_settings: Settings) -> None:
    client = FakeClient()
    runner = DockerSandboxRunner(docker_settings, client=client)
    result = runner.run(tmp_path, ["npm", "ci"], phase="install", network_disabled=False)
    assert result.status == "passed"
    assert client.containers.created[0]["network_disabled"] is False


def test_test_phase_cannot_enable_network(tmp_path: Path, docker_settings: Settings) -> None:
    client = FakeClient()
    runner = DockerSandboxRunner(docker_settings, client=client)
    with pytest.raises(SandboxPolicyError, match="network disabled"):
        runner.run(tmp_path, ["node", "-e", "1"], phase="test", network_disabled=False)
    assert client.containers.created == []


def test_timeout_kills_and_removes_container(tmp_path: Path, docker_settings: Settings) -> None:
    container = FakeContainer(wait_error=requests.exceptions.ReadTimeout("slow"))
    client = FakeClient(container=container)
    runner = DockerSandboxRunner(docker_settings, client=client)

    result = runner.run(tmp_path, ["node", "-e", "1"], timeout_seconds=7)

    assert result.status == "timeout"
    assert result.timed_out is True
    assert result.exit_code is None
    assert "7s timeout" in (result.error or "")
    assert container.killed is True
    assert container.removed is True


def test_docker_error_is_reported_and_container_cleaned(
    tmp_path: Path, docker_settings: Settings
) -> None:
    container = FakeContainer()
    client = FakeClient(container=container, create_error=docker.errors.DockerException("boom"))
    runner = DockerSandboxRunner(docker_settings, client=client)

    result = runner.run(tmp_path, ["node", "-e", "1"])

    assert result.status == "error"
    assert "boom" in (result.error or "")
    assert container.removed is False  # create never returned a container


def test_wait_error_returns_error_status(tmp_path: Path, docker_settings: Settings) -> None:
    container = FakeContainer(wait_error=docker.errors.DockerException("wait failed"))
    client = FakeClient(container=container)
    runner = DockerSandboxRunner(docker_settings, client=client)
    result = runner.run(tmp_path, ["node", "-e", "1"])
    assert result.status == "error"
    assert "wait failed" in (result.error or "")
    assert container.removed is True


def test_environment_rejects_secret_names(tmp_path: Path, docker_settings: Settings) -> None:
    runner = DockerSandboxRunner(docker_settings, client=FakeClient())
    with pytest.raises(SandboxPolicyError, match="secret-looking"):
        runner.run(tmp_path, ["node", "-e", "1"], env={"GITHUB_TOKEN": "nope"})


def test_unknown_phase_and_bad_command_are_rejected(
    tmp_path: Path, docker_settings: Settings
) -> None:
    runner = DockerSandboxRunner(docker_settings, client=FakeClient())
    with pytest.raises(SandboxPolicyError, match="phase"):
        runner.run(tmp_path, ["node", "-e", "1"], phase="deploy")
    with pytest.raises(SandboxPolicyError, match="cannot be empty"):
        runner.run(tmp_path, [])
    with pytest.raises(SandboxPolicyError, match="NUL"):
        runner.run(tmp_path, ["node", "-e", "1\x00"])


def test_missing_workspace_is_rejected(tmp_path: Path, docker_settings: Settings) -> None:
    runner = DockerSandboxRunner(docker_settings, client=FakeClient())
    with pytest.raises(SandboxPolicyError, match="not a directory"):
        runner.run(tmp_path / "missing", ["node", "-e", "1"])
    with pytest.raises(SandboxPolicyError, match="only permits"):
        runner.run(tmp_path, ["sh", "-c", "echo hi"])


def test_available_reports_daemon_error(docker_settings: Settings) -> None:
    client = FakeClient(ping_error=docker.errors.DockerException("no socket"))
    runner = DockerSandboxRunner(docker_settings, client=client)
    ok, message = runner.available()
    assert ok is False
    assert "no socket" in message


def test_available_reports_success(docker_settings: Settings) -> None:
    runner = DockerSandboxRunner(docker_settings, client=FakeClient())
    assert runner.available() == (True, "")


def test_ensure_image_pulls_only_when_missing(docker_settings: Settings) -> None:
    images = FakeImages(present=False)
    runner = DockerSandboxRunner(docker_settings, client=FakeClient(images=images))
    runner.ensure_image()
    assert images.pulled == ["test-image"]

    present = FakeImages(present=True)
    runner = DockerSandboxRunner(docker_settings, client=FakeClient(images=present))
    runner.ensure_image()
    assert present.pulled == []


def test_from_env_failure_is_wrapped(
    monkeypatch: pytest.MonkeyPatch, docker_settings: Settings
) -> None:
    def explode() -> None:
        raise docker.errors.DockerException("no daemon")

    monkeypatch.setattr("app.sandbox.docker.docker.from_env", explode)
    runner = DockerSandboxRunner(docker_settings)
    assert runner.available()[0] is False
    with pytest.raises(SandboxUnavailable, match="no daemon"):
        _ = runner.client


def test_truncate_log_keeps_both_ends() -> None:
    text = "a" * 100 + "b" * 100
    truncated = truncate_log(text, 80)
    assert len(truncated) < len(text)
    assert truncated.startswith("a" * 20)
    assert truncated.endswith("b" * 60)
    assert "characters truncated" in truncated
    assert truncate_log("short", 80) == "short"


def test_logs_failures_and_non_bytes_are_handled(tmp_path: Path, docker_settings: Settings) -> None:
    container = FakeContainer(logs_error=docker.errors.DockerException("logs"))
    runner = DockerSandboxRunner(docker_settings, client=FakeClient(container=container))
    result = runner.run(tmp_path, ["node", "-e", "1"])
    assert result.stdout == ""
    assert result.stderr == ""

    container = FakeContainer(stdout="text output", stderr="text error")
    runner = DockerSandboxRunner(docker_settings, client=FakeClient(container=container))
    result = runner.run(tmp_path, ["node", "-e", "1"])
    assert result.stdout == "text output"
    assert result.stderr == "text error"


def test_cleanup_errors_do_not_mask_result(tmp_path: Path, docker_settings: Settings) -> None:
    container = FakeContainer(remove_error=docker.errors.DockerException("remove"))
    runner = DockerSandboxRunner(docker_settings, client=FakeClient(container=container))
    result = runner.run(tmp_path, ["node", "-e", "1"])
    assert result.status == "passed"


def test_zero_timeout_is_rejected(tmp_path: Path, docker_settings: Settings) -> None:
    runner = DockerSandboxRunner(docker_settings, client=FakeClient())
    with pytest.raises(SandboxPolicyError, match="positive"):
        runner.run(tmp_path, ["node", "-e", "1"], timeout_seconds=0)


def test_client_lazy_initialization(
    monkeypatch: pytest.MonkeyPatch, docker_settings: Settings
) -> None:
    fake = FakeClient()
    monkeypatch.setattr("app.sandbox.docker.docker.from_env", lambda: fake)
    runner = DockerSandboxRunner(docker_settings)
    assert runner.client is fake
    assert runner.available() == (True, "")


def test_factory_selects_backend(settings: Settings, docker_settings: Settings) -> None:
    assert isinstance(build_sandbox(settings), LocalSandboxRunner)
    assert isinstance(build_sandbox(docker_settings), DockerSandboxRunner)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"timeout_seconds": 0}, "timeout"),
        ({"memory_mb": 32}, "memory"),
        ({"cpus": 0}, "cpus"),
        ({"pids_limit": 1}, "pids"),
    ],
)
def test_sandbox_limits_validation(kwargs: dict[str, int], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        SandboxLimits(**kwargs)


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        ((), "empty"),
        (tuple(str(index) for index in range(65)), "too many"),
        (("node", 1), "strings"),
        (("node", "a\x00b"), "NUL"),
        (("node", "x" * 4097), "too long"),
    ],
)
def test_sandbox_command_validation(argv: tuple[object, ...], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        SandboxCommand(argv)  # type: ignore[arg-type]


def test_sandbox_result_to_dict() -> None:
    result = SandboxResult(
        phase="test",
        command=("node", "-e", "1"),
        status="passed",
        exit_code=0,
        timed_out=False,
        duration_ms=4,
        stdout="ok",
        stderr="",
        network_disabled=True,
        isolation="docker",
    )
    payload = result.to_dict()
    assert payload["command"] == ["node", "-e", "1"]
    assert payload["status"] == "passed"
    assert result.passed is True


def test_security_rejects_bad_environment() -> None:
    from app.sandbox.security import docker_environment

    with pytest.raises(SandboxPolicyError, match="strings"):
        docker_environment({1: "x"})  # type: ignore[dict-item]
    with pytest.raises(SandboxPolicyError, match="invalid"):
        docker_environment({"FOO=BAR": "x"})
    with pytest.raises(SandboxPolicyError, match="invalid"):
        docker_environment({"FOO": "a\x00b"})
    with pytest.raises(SandboxPolicyError, match="not allowed"):
        docker_environment({"DATABASE_URL": "postgres://secret"})


def test_local_command_normalization_allows_cmd_suffix() -> None:
    from app.sandbox.security import validate_executable

    assert validate_executable(("npm.cmd", "ci")) == "npm.cmd"


def test_local_available_and_validation_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, settings: Settings
) -> None:
    runner = LocalSandboxRunner(settings)
    assert runner.available()[0] is True
    monkeypatch.setattr("app.sandbox.local.shutil.which", lambda _: None)
    assert runner.available() == (False, "node is not installed")
    with pytest.raises(SandboxPolicyError, match="not found"):
        runner.run(tmp_path, ["node", "-e", "1"])
    with pytest.raises(SandboxPolicyError, match="phase"):
        LocalSandboxRunner(settings).run(tmp_path, ["node", "-e", "1"], phase="deploy")
    with pytest.raises(SandboxPolicyError, match="positive"):
        LocalSandboxRunner(settings).run(tmp_path, ["node", "-e", "1"], timeout_seconds=0)


def test_kill_process_tree_finished_process_is_noop(tmp_path: Path) -> None:
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    process = subprocess.Popen(["node", "-e", "0"], cwd=tmp_path)
    process.wait()
    _kill_process_tree(process)  # must not raise or touch an exited process
    assert process.returncode == 0


def test_local_runner_runs_node_in_temp_workspace(tmp_path: Path, settings: Settings) -> None:
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    runner = LocalSandboxRunner(settings)
    result = runner.run(
        tmp_path,
        ["node", "-e", "console.log(process.env.PRGUARD_TEST_VALUE)"],
        env={"PRGUARD_TEST_VALUE": "safe-value"},
    )
    assert result.status == "passed"
    assert result.stdout.strip() == "safe-value"
    assert result.network_disabled is False
    assert "NOT a security boundary" in result.isolation


def test_local_runner_reports_failure_and_timeout(tmp_path: Path, settings: Settings) -> None:
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    runner = LocalSandboxRunner(settings)
    failed = runner.run(tmp_path, ["node", "-e", "process.exit(3)"])
    assert failed.status == "failed"
    assert failed.exit_code == 3

    timed_out = runner.run(
        tmp_path, ["node", "-e", "setTimeout(() => {}, 10000)"], timeout_seconds=1
    )
    assert timed_out.status == "timeout"
    assert timed_out.timed_out is True


def test_local_runner_rejects_disallowed_executable(tmp_path: Path, settings: Settings) -> None:
    runner = LocalSandboxRunner(settings)
    with pytest.raises(SandboxPolicyError, match="only permits"):
        runner.run(tmp_path, ["python", "-c", "print(1)"])
    with pytest.raises(SandboxPolicyError, match="bare executable"):
        runner.run(tmp_path, ["./node", "-e", "1"])


def _docker_daemon_available() -> bool:
    try:
        client = docker.from_env()
        client.ping()
    except Exception:
        return False
    return True


@pytest.mark.docker
@pytest.mark.skipif(not _docker_daemon_available(), reason="Docker daemon is not available")
def test_real_docker_container_is_nonroot_readonly_and_offline(
    tmp_path: Path, docker_settings: Settings
) -> None:
    image = os.environ.get("PRGUARD_TEST_SANDBOX_IMAGE", "prguard-sandbox:node20")
    real_settings = docker_settings.model_copy(update={"sandbox_image": image})
    runner = DockerSandboxRunner(real_settings)
    try:
        runner.client.images.get(real_settings.sandbox_image)
    except docker.errors.ImageNotFound:
        pytest.skip(f"{real_settings.sandbox_image} is not built")

    nonroot = runner.run(
        tmp_path,
        ["node", "-e", "console.log(process.getuid())"],
        phase="test",
        timeout_seconds=30,
    )
    assert nonroot.status == "passed"
    assert nonroot.stdout.strip() == "10001"

    readonly = runner.run(
        tmp_path,
        ["node", "-e", "require('fs').writeFileSync('/etc/prguard', 'x')"],
        phase="test",
        timeout_seconds=30,
    )
    assert readonly.status == "failed"

    offline = runner.run(
        tmp_path,
        [
            "node",
            "-e",
            "fetch('https://example.com').then(() => process.exit(1)).catch(() => process.exit(0))",
        ],
        phase="test",
        timeout_seconds=30,
    )
    assert offline.status == "passed"
