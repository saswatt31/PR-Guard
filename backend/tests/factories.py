"""Small, explicit GitHub payload builders for tests."""

from __future__ import annotations

from typing import Any


def pull_request_payload(
    *,
    action: str = "opened",
    number: int = 7,
    repo: str = "acme/demo",
    head_sha: str = "a" * 40,
    base_sha: str = "b" * 40,
    head_repo: str | None = None,
    fork: bool = False,
    installation_id: int = 99,
) -> dict[str, Any]:
    owner, name = repo.split("/", 1)
    head_full_name = head_repo or ("fork/demo" if fork else repo)
    return {
        "action": action,
        "number": number,
        "pull_request": {
            "number": number,
            "head": {
                "sha": head_sha,
                "ref": "feature",
                "repo": {"full_name": head_full_name, "fork": fork},
            },
            "base": {"sha": base_sha},
            "user": {"login": "octocat"},
            "draft": False,
        },
        "repository": {
            "full_name": repo,
            "name": name,
            "owner": {"login": owner},
        },
        "installation": {"id": installation_id},
        "sender": {"login": "octocat"},
    }
