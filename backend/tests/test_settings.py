from pathlib import Path

import pytest

from app.settings import Settings


def test_settings_defaults_are_safe(tmp_path: Path) -> None:
    cfg = Settings(_env_file=None, database_url=f"sqlite:///{tmp_path / 'x.db'}")
    assert cfg.llm_provider == "fake"
    assert cfg.sandbox_mode == "docker"
    assert cfg.allow_fork_prs is False
    assert cfg.max_llm_calls == 24
    assert cfg.worker_enabled is True


def test_cors_origin_list_strips_whitespace() -> None:
    cfg = Settings(_env_file=None, cors_origins="http://a.test, http://b.test ,")
    assert cfg.cors_origin_list == ["http://a.test", "http://b.test"]


def test_inline_private_key_unescapes_newlines() -> None:
    cfg = Settings(
        _env_file=None,
        github_private_key_pem="-----BEGIN KEY-----\\nabc\\n-----END KEY-----",
    )
    assert cfg.github_private_key == "-----BEGIN KEY-----\nabc\n-----END KEY-----"


def test_private_key_can_be_loaded_from_file(tmp_path: Path) -> None:
    key_file = tmp_path / "app.pem"
    key_file.write_text("pem-content", encoding="utf-8")
    cfg = Settings(_env_file=None, github_private_key_path=key_file, github_private_key_pem=None)
    assert cfg.github_private_key == "pem-content"


def test_missing_private_key_returns_none(tmp_path: Path) -> None:
    cfg = Settings(
        _env_file=None,
        github_private_key_path=tmp_path / "missing.pem",
        github_private_key_pem=None,
    )
    assert cfg.github_private_key is None


def test_require_github_app_reports_missing_values() -> None:
    cfg = Settings(_env_file=None, github_app_id=None, github_private_key_pem=None)
    with pytest.raises(RuntimeError, match="GITHUB_APP_ID"):
        cfg.require_github_app()


def test_require_github_app_accepts_configured_values() -> None:
    cfg = Settings(_env_file=None, github_app_id="1", github_private_key_pem="key")
    cfg.require_github_app()
