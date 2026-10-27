"""Typed results shared by sandbox backends."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class SandboxPhase(StrEnum):
    INSTALL = "install"
    TEST = "test"


class SandboxStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    ERROR = "error"


@dataclass(frozen=True)
class SandboxResult:
    phase: str
    command: tuple[str, ...]
    status: str
    exit_code: int | None
    timed_out: bool
    duration_ms: int
    stdout: str
    stderr: str
    network_disabled: bool
    isolation: str
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.status == SandboxStatus.PASSED

    def to_dict(self) -> dict[str, object]:
        return {
            "phase": self.phase,
            "command": list(self.command),
            "status": self.status,
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "duration_ms": self.duration_ms,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "network_disabled": self.network_disabled,
            "isolation": self.isolation,
            "error": self.error,
        }


@dataclass(frozen=True)
class SandboxLimits:
    timeout_seconds: int = 180
    memory_mb: int = 1024
    cpus: float = 1.0
    pids_limit: int = 256
    max_log_chars: int = 120_000

    def __post_init__(self) -> None:
        if self.timeout_seconds < 1:
            raise ValueError("timeout_seconds must be positive")
        if self.memory_mb < 64:
            raise ValueError("memory_mb must be at least 64")
        if not 0 < self.cpus <= 16:
            raise ValueError("cpus must be between 0 and 16")
        if self.pids_limit < 16:
            raise ValueError("pids_limit must be at least 16")


@dataclass(frozen=True)
class SandboxCommand:
    """A validated argv. The sandbox never accepts a shell string."""

    argv: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.argv:
            raise ValueError("sandbox command cannot be empty")
        if len(self.argv) > 64:
            raise ValueError("sandbox command has too many arguments")
        for argument in self.argv:
            if not isinstance(argument, str):
                raise ValueError("sandbox command arguments must be strings")
            if "\x00" in argument:
                raise ValueError("sandbox command contains a NUL byte")
            if len(argument) > 4096:
                raise ValueError("sandbox command argument is too long")
