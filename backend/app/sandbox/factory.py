"""Sandbox backend selection."""

from __future__ import annotations

from app.sandbox.docker import DockerSandboxRunner
from app.sandbox.local import LocalSandboxRunner
from app.settings import Settings

SandboxRunner = DockerSandboxRunner | LocalSandboxRunner


def build_sandbox(settings: Settings) -> SandboxRunner:
    if settings.sandbox_mode == "docker":
        return DockerSandboxRunner(settings)
    return LocalSandboxRunner(settings)
