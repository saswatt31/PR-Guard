"""Repository-level `.prguard.yml` configuration.

The file comes from the pull-request head, so every value is untrusted. Parsing is
strict, commands are argv lists, and all paths must stay inside the repository.
"""

from __future__ import annotations

import shlex
from pathlib import Path, PurePosixPath
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.sandbox.errors import SandboxPolicyError
from app.sandbox.security import validate_command, validate_executable

MAX_CONFIG_BYTES = 64 * 1024
CONFIG_NAMES = (".prguard.yml", ".prguard.yaml")
DEFAULT_TEST_COMMAND = (
    "npx",
    "vitest",
    "run",
    "--coverage",
    "--reporter=json",
    "--outputFile=vitest-results.json",
)


class RepoConfigError(ValueError):
    """The repository config exists but cannot be used safely."""


def _safe_relative(value: str, field: str) -> str:
    pure = PurePosixPath(value.replace("\\", "/"))
    if not value or pure.is_absolute() or ".." in pure.parts:
        raise ValueError(f"{field} must be a relative path inside the repository")
    return pure.as_posix()


class RepoConfig(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    enabled_paths: tuple[str, ...] = ("**",)
    install_command: tuple[str, ...] = ("npm", "ci")
    test_command: tuple[str, ...] = DEFAULT_TEST_COMMAND
    results_file: str = "vitest-results.json"
    coverage_file: str = "coverage/coverage-final.json"
    max_fix_attempts: int = Field(default=3, ge=0, le=3)
    max_tests: int = Field(default=8, ge=1, le=20)
    include_ui_tests: bool = False
    review_code: bool = True
    post_comment: bool = True
    sandbox_install_network: bool = True
    run_baseline_coverage: bool = True
    max_llm_calls: int | None = Field(default=None, ge=1, le=100)
    max_total_tokens: int | None = Field(default=None, ge=1000, le=2_000_000)
    max_cost_usd: float | None = Field(default=None, ge=0, le=100)

    @field_validator("enabled_paths", mode="before")
    @classmethod
    def _validate_paths(cls, value: Any) -> tuple[str, ...]:
        if value is None:
            return ("**",)
        if not isinstance(value, (list, tuple)):
            raise ValueError("enabled_paths must be a list of glob patterns")
        if len(value) > 50:
            raise ValueError("enabled_paths has too many patterns")
        patterns: list[str] = []
        for raw in value:
            if not isinstance(raw, str):
                raise ValueError("enabled_paths entries must be strings")
            pattern = raw.strip().replace("\\", "/")
            if not pattern or len(pattern) > 200:
                raise ValueError("enabled_paths entry is empty or too long")
            if pattern.startswith("/") or ".." in PurePosixPath(pattern).parts:
                raise ValueError("enabled_paths must stay inside the repository")
            patterns.append(pattern)
        return tuple(patterns)

    @field_validator("install_command", "test_command", mode="before")
    @classmethod
    def _parse_command(cls, value: Any) -> tuple[str, ...]:
        if isinstance(value, str):
            try:
                argv = tuple(shlex.split(value, posix=True))
            except ValueError as exc:
                raise ValueError(f"command cannot be parsed: {exc}") from exc
        elif isinstance(value, (list, tuple)):
            argv = tuple(value)
        else:
            raise ValueError("command must be a string or a list of strings")
        try:
            validated = validate_command(argv)
            validate_executable(validated)
        except SandboxPolicyError as exc:
            raise ValueError(str(exc)) from exc
        return validated

    @field_validator("results_file", "coverage_file", mode="before")
    @classmethod
    def _validate_output_path(cls, value: Any, info: Any) -> str:
        if not isinstance(value, str):
            raise ValueError(f"{info.field_name} must be a string")
        relative = _safe_relative(value, info.field_name)
        if not relative.lower().endswith(".json"):
            raise ValueError(f"{info.field_name} must end in .json")
        return relative

    def to_public_dict(self) -> dict[str, Any]:
        data = self.model_dump()
        for key in ("enabled_paths", "install_command", "test_command"):
            data[key] = list(data[key])
        return data


def load_repo_config(root: Path) -> RepoConfig:
    """Read the first supported config file; missing means defaults."""

    for name in CONFIG_NAMES:
        path = root / name
        if not path.is_file():
            continue
        try:
            size = path.stat().st_size
            if size > MAX_CONFIG_BYTES:
                raise RepoConfigError(f"{name} is larger than {MAX_CONFIG_BYTES} bytes")
            raw = path.read_text(encoding="utf-8")
            data = yaml.safe_load(raw)
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
            raise RepoConfigError(f"{name} could not be read: {exc}") from exc
        if data is None:
            return RepoConfig()
        if not isinstance(data, dict):
            raise RepoConfigError(f"{name} must contain a mapping")
        try:
            return RepoConfig.model_validate(data)
        except ValidationError as exc:
            raise RepoConfigError(f"{name} is invalid: {exc}") from exc
    return RepoConfig()
