"""Process-wide configuration loaded from environment variables / .env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime configuration in one typed place.

    Secrets are plain ``str`` fields; they are never logged or serialized to the
    database. Tests construct ``Settings(_env_file=None, ...)`` explicitly.
    """

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    app_env: Literal["development", "test", "production"] = "development"
    database_url: str = "sqlite:///./data/prguard.db"
    demo_mode: bool = False
    allow_fork_prs: bool = False
    log_level: str = "INFO"

    # GitHub App
    github_app_id: str | None = None
    github_private_key_path: Path | None = None
    github_private_key_pem: str | None = Field(default=None, alias="GITHUB_PRIVATE_KEY")
    github_webhook_secret: str = "change-me"
    github_token: str | None = None  # optional PAT for demo capture only
    github_api_url: str = "https://api.github.com"

    # LLM
    llm_provider: Literal["fake", "groq", "anthropic"] = "fake"
    groq_api_key: str | None = None
    groq_model: str = "llama-3.3-70b-versatile"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-20250514"
    max_llm_calls: int = 24
    max_total_tokens: int = 120_000
    max_cost_usd: float = 0.75

    # Sandbox
    sandbox_mode: Literal["docker", "local"] = "docker"
    sandbox_image: str = "prguard-sandbox:node20"
    sandbox_timeout_seconds: int = 180
    sandbox_install_timeout_seconds: int = 300
    sandbox_memory_mb: int = 1024
    sandbox_cpus: float = 1.0
    sandbox_pids_limit: int = 256
    sandbox_install_network: bool = True
    sandbox_keep_failed: bool = False
    max_repo_tarball_bytes: int = 50 * 1024 * 1024
    max_webhook_bytes: int = 10 * 1024 * 1024

    # Dashboard / links
    cors_origins: str = "http://localhost:3000"
    dashboard_base_url: str = "http://localhost:3000"
    public_api_url: str = "http://localhost:8000"

    # Worker
    worker_poll_seconds: float = 1.0
    job_max_attempts: int = 2
    worker_enabled: bool = True

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def github_private_key(self) -> str | None:
        """Prefer an inline PEM (production secret store), fall back to a file."""

        if self.github_private_key_pem:
            return self.github_private_key_pem.replace("\\n", "\n")
        if self.github_private_key_path and self.github_private_key_path.exists():
            return self.github_private_key_path.read_text(encoding="utf-8")
        return None

    def require_github_app(self) -> None:
        missing = []
        if not self.github_app_id:
            missing.append("GITHUB_APP_ID")
        if not self.github_private_key:
            missing.append("GITHUB_PRIVATE_KEY(_PATH)")
        if missing:
            raise RuntimeError(f"GitHub App is not configured; missing {', '.join(missing)}")


@lru_cache
def get_settings() -> Settings:
    return Settings()
