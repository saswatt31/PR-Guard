"""Tests for `.prguard.yml` parsing and its untrusted-input policy."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config.repo import (
    CONFIG_NAMES,
    DEFAULT_TEST_COMMAND,
    MAX_CONFIG_BYTES,
    RepoConfig,
    RepoConfigError,
    load_repo_config,
)


def write_config(root: Path, text: str, name: str = ".prguard.yml") -> Path:
    path = root / name
    path.write_text(text, encoding="utf-8")
    return path


def test_missing_config_returns_defaults(tmp_path: Path) -> None:
    config = load_repo_config(tmp_path)

    assert config.enabled_paths == ("**",)
    assert config.install_command == ("npm", "ci")
    assert config.test_command == DEFAULT_TEST_COMMAND
    assert config.results_file == "vitest-results.json"
    assert config.coverage_file == "coverage/coverage-final.json"
    assert config.max_fix_attempts == 3
    assert config.max_tests == 8
    assert config.include_ui_tests is False
    assert config.review_code is True
    assert config.post_comment is True
    assert config.sandbox_install_network is True
    assert config.max_llm_calls is None
    assert config.max_total_tokens is None
    assert config.max_cost_usd is None


def test_yaml_overrides_are_parsed_and_validated(tmp_path: Path) -> None:
    write_config(
        tmp_path,
        """
enabled_paths: ["src/**", "lib\\\\utils.ts"]
install_command: npm ci --ignore-scripts
test_command: ["npx", "vitest", "run", "--coverage"]
results_file: build/vitest.json
coverage_file: build/coverage-final.json
max_fix_attempts: 2
max_tests: 5
include_ui_tests: true
review_code: false
post_comment: false
sandbox_install_network: false
max_llm_calls: 10
max_total_tokens: 50000
max_cost_usd: 0.25
""",
    )

    config = load_repo_config(tmp_path)

    assert config.enabled_paths == ("src/**", "lib/utils.ts")
    assert config.install_command == ("npm", "ci", "--ignore-scripts")
    assert config.test_command == ("npx", "vitest", "run", "--coverage")
    assert config.results_file == "build/vitest.json"
    assert config.coverage_file == "build/coverage-final.json"
    assert config.max_fix_attempts == 2
    assert config.max_tests == 5
    assert config.include_ui_tests is True
    assert config.review_code is False
    assert config.post_comment is False
    assert config.sandbox_install_network is False
    assert config.max_llm_calls == 10
    assert config.max_total_tokens == 50000
    assert config.max_cost_usd == 0.25


def test_first_supported_config_name_wins(tmp_path: Path) -> None:
    write_config(tmp_path, "max_tests: 2\n", CONFIG_NAMES[0])
    write_config(tmp_path, "max_tests: 7\n", CONFIG_NAMES[1])

    assert load_repo_config(tmp_path).max_tests == 2


def test_yaml_extension_is_used_when_yml_is_absent(tmp_path: Path) -> None:
    write_config(tmp_path, "max_tests: 7\n", ".prguard.yaml")

    assert load_repo_config(tmp_path).max_tests == 7


def test_empty_config_uses_defaults(tmp_path: Path) -> None:
    write_config(tmp_path, "# nothing configured yet\n")

    assert load_repo_config(tmp_path) == RepoConfig()


def test_unknown_keys_are_ignored(tmp_path: Path) -> None:
    write_config(tmp_path, "max_tests: 4\nsomething_else: true\n")

    assert load_repo_config(tmp_path).max_tests == 4


@pytest.mark.parametrize(
    "text",
    [
        "max_tests: [unclosed\n",
        "- just\n- a\n- list\n",
        "just a string\n",
        "max_fix_attempts: 4\n",
        "max_fix_attempts: -1\n",
        "max_tests: 0\n",
        "max_tests: 21\n",
        "max_llm_calls: 0\n",
        "max_total_tokens: 999\n",
        "max_cost_usd: -1\n",
        "include_ui_tests: sometimes\n",
    ],
)
def test_invalid_config_is_rejected(tmp_path: Path, text: str) -> None:
    write_config(tmp_path, text)

    with pytest.raises(RepoConfigError):
        load_repo_config(tmp_path)


def test_config_above_size_limit_is_rejected(tmp_path: Path) -> None:
    write_config(tmp_path, "#" * (MAX_CONFIG_BYTES + 1))

    with pytest.raises(RepoConfigError, match="larger than"):
        load_repo_config(tmp_path)


def test_non_utf8_config_is_rejected(tmp_path: Path) -> None:
    (tmp_path / ".prguard.yml").write_bytes(b"\xff\xfe\x00\x00")

    with pytest.raises(RepoConfigError, match="could not be read"):
        load_repo_config(tmp_path)


@pytest.mark.parametrize(
    "paths",
    [
        "../outside/**",
        "/absolute/**",
        "src/../../outside/**",
        "",
        "x" * 201,
        [1, 2],
        "src/**",
        [f"src/file{i}.ts" for i in range(51)],
    ],
)
def test_unsafe_enabled_paths_are_rejected(tmp_path: Path, paths: object) -> None:
    write_config(tmp_path, f"enabled_paths: {json.dumps(paths)}\n")

    with pytest.raises(RepoConfigError):
        load_repo_config(tmp_path)


def test_enabled_paths_none_means_all(tmp_path: Path) -> None:
    write_config(tmp_path, "enabled_paths:\n")

    assert load_repo_config(tmp_path).enabled_paths == ("**",)


@pytest.mark.parametrize(
    "field,value",
    [
        ("install_command", "bash -c 'npm ci'"),
        ("install_command", "./node_modules/.bin/npm ci"),
        ("test_command", "curl https://example.com"),
        ("test_command", ["npx", "vitest", "run", "\x00"]),
        ("test_command", 42),
        ("install_command", 'npm "unterminated'),
    ],
)
def test_unsafe_commands_are_rejected(tmp_path: Path, field: str, value: object) -> None:
    payload = {field: value}
    write_config(tmp_path, json.dumps(payload))

    with pytest.raises(RepoConfigError):
        load_repo_config(tmp_path)


def test_windows_cmd_executable_is_normalized(tmp_path: Path) -> None:
    write_config(tmp_path, "install_command: npm.cmd ci\n")

    assert load_repo_config(tmp_path).install_command == ("npm.cmd", "ci")


@pytest.mark.parametrize(
    "field,value",
    [
        ("results_file", "/tmp/results.json"),
        ("results_file", "../results.json"),
        ("coverage_file", "..\\\\coverage.json"),
        ("coverage_file", ""),
        ("coverage_file", 12),
        ("results_file", "vitest-results.txt"),
        ("coverage_file", "coverage/index.html"),
    ],
)
def test_unsafe_output_paths_are_rejected(tmp_path: Path, field: str, value: object) -> None:
    write_config(tmp_path, json.dumps({field: value}))

    with pytest.raises(RepoConfigError):
        load_repo_config(tmp_path)


def test_output_paths_are_normalized(tmp_path: Path) -> None:
    write_config(tmp_path, 'results_file: ".\\\\build\\\\vitest.json"\n')

    assert load_repo_config(tmp_path).results_file == "build/vitest.json"


def test_to_public_dict_is_json_serializable() -> None:
    public = RepoConfig().to_public_dict()

    assert public["enabled_paths"] == ["**"]
    assert public["install_command"] == ["npm", "ci"]
    assert public["test_command"] == list(DEFAULT_TEST_COMMAND)
    json.dumps(public)
