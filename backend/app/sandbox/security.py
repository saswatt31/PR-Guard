"""Shared sandbox policy helpers.

Sandbox commands are argv lists, never shell strings. Environment variables are
allow-listed (local mode) or explicitly supplied (Docker), and secret-looking names are
always rejected so a worker bug cannot leak GitHub/LLM credentials into test code.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path

from app.sandbox.errors import SandboxPolicyError
from app.sandbox.models import SandboxCommand

SECRET_ENV_RE = re.compile(
    r"(TOKEN|SECRET|PASSWORD|PASSWD|PRIVATE|CREDENTIAL|AUTH|COOKIE|SESSION|API_?KEY)",
    re.IGNORECASE,
)
SAFE_EXTRA_ENV_RE = re.compile(
    r"^(CI|NODE_ENV|NODE_OPTIONS|TZ|LANG|LC_ALL|"
    r"NPM_CONFIG_[A-Z0-9_]+|VITEST_[A-Z0-9_]+|PLAYWRIGHT_[A-Z0-9_]+|PRGUARD_[A-Z0-9_]+)$"
)
# Needed by Node/npm on Windows; never includes application secrets.
LOCAL_ENV_ALLOWLIST = {
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "WINDIR",
    "COMSPEC",
    "TEMP",
    "TMP",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
    "PROGRAMDATA",
    "HOME",
    "LANG",
    "LC_ALL",
}
EXECUTABLE_ALLOWLIST = {"node", "npm", "npx", "pnpm", "yarn", "vitest", "playwright"}
BASE_DOCKER_ENV = {
    "CI": "1",
    "HOME": "/tmp",
    "NO_COLOR": "1",
    "FORCE_COLOR": "0",
    "NPM_CONFIG_AUDIT": "false",
    "NPM_CONFIG_CACHE": "/tmp/npm",
    "NPM_CONFIG_FUND": "false",
    "NPM_CONFIG_UPDATE_NOTIFIER": "false",
}


def validate_command(command: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    try:
        return SandboxCommand(tuple(command)).argv
    except ValueError as exc:
        raise SandboxPolicyError(str(exc)) from exc


def validate_workspace(workspace: Path) -> Path:
    resolved = workspace.resolve()
    if not resolved.is_dir():
        raise SandboxPolicyError(f"sandbox workspace is not a directory: {workspace}")
    return resolved


def _safe_extra_env(extra: Mapping[str, str] | None) -> dict[str, str]:
    if not extra:
        return {}
    clean: dict[str, str] = {}
    for key, value in extra.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise SandboxPolicyError("sandbox environment keys and values must be strings")
        if SECRET_ENV_RE.search(key):
            raise SandboxPolicyError(f"refusing to pass secret-looking environment variable: {key}")
        if "\x00" in key or "\x00" in value or "=" in key:
            raise SandboxPolicyError("sandbox environment contains invalid characters")
        if not SAFE_EXTRA_ENV_RE.match(key):
            raise SandboxPolicyError(
                f"environment variable is not allowed by the sandbox policy: {key}"
            )
        clean[key] = value
    return clean


def docker_environment(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """Only the fixed container baseline plus explicitly approved variables."""

    environment = dict(BASE_DOCKER_ENV)
    environment.update(_safe_extra_env(extra))
    return environment


def local_environment(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """Copy only host variables needed to run Node, then add approved extras."""

    environment = {
        key: value for key, value in os.environ.items() if key.upper() in LOCAL_ENV_ALLOWLIST
    }
    environment.setdefault("CI", "1")
    environment.update(_safe_extra_env(extra))
    return environment


def validate_executable(command: tuple[str, ...]) -> str:
    executable = Path(command[0]).name.lower()
    if executable.endswith(".cmd"):
        executable = executable[:-4]
    if executable not in EXECUTABLE_ALLOWLIST:
        raise SandboxPolicyError(
            f"sandbox only permits {sorted(EXECUTABLE_ALLOWLIST)}; got {command[0]}"
        )
    if any(separator in command[0] for separator in ("/", "\\")):
        raise SandboxPolicyError("sandbox command must be a bare executable name")
    return command[0]


def truncate_log(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    head = limit // 4
    tail = limit - head
    return f"{text[:head]}\n... [{len(text) - limit} characters truncated] ...\n{text[-tail:]}"
