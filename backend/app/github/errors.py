"""Errors shared by GitHub helpers.

Messages are safe to persist: they never include Authorization headers or tokens.
"""

from __future__ import annotations


class GitHubError(RuntimeError):
    pass


class GitHubAuthError(GitHubError):
    pass


class GitHubAPIError(GitHubError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"GitHub API {status_code}: {message}")
        self.status_code = status_code
        self.message = message


class RepoExtractionError(ValueError):
    pass
