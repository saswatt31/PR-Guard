"""Typed GitHub REST client used by the worker.

Only the endpoints PR-Guard needs are implemented. Tokens live in memory and are never
passed to the sandbox or written to the database.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx

from app.github.auth import build_app_jwt
from app.github.errors import GitHubAPIError, GitHubAuthError
from app.settings import Settings


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


@dataclass(frozen=True)
class PostedComment:
    id: int
    html_url: str


class GitHubClient:
    def __init__(self, settings: Settings, http: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._http = http or httpx.AsyncClient(timeout=httpx.Timeout(30.0), follow_redirects=True)
        self._owns_http = http is None
        self._tokens: dict[int, tuple[str, datetime]] = {}

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def __aenter__(self) -> GitHubClient:
        return self

    async def __aexit__(self, *_exc) -> None:
        await self.aclose()

    def _url(self, path: str) -> str:
        return f"{self._settings.github_api_url.rstrip('/')}/{path.lstrip('/')}"

    @staticmethod
    def _base_headers() -> dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "pr-guard",
        }

    async def installation_token(self, installation_id: int, *, force: bool = False) -> str:
        cached = self._tokens.get(installation_id)
        if cached and not force and cached[1] > datetime.now(UTC):
            return cached[0]

        app_jwt = build_app_jwt(
            self._settings.github_app_id or "", self._settings.github_private_key
        )
        response = await self._http.post(
            self._url(f"/app/installations/{installation_id}/access_tokens"),
            headers={
                **self._base_headers(),
                "Authorization": f"Bearer {app_jwt}",
            },
        )
        if response.status_code >= 400:
            raise GitHubAPIError(response.status_code, _safe_message(response))
        data = response.json()
        token = data.get("token")
        expires_at = data.get("expires_at")
        if not token or not expires_at:
            raise GitHubAuthError("installation token response was missing token/expires_at")
        expiry = _parse_time(expires_at) - timedelta(minutes=1)
        # Refresh one minute early rather than using a token that expires mid-request.
        self._tokens[installation_id] = (token, expiry)
        return token

    async def _repo_request(
        self,
        method: str,
        path: str,
        installation_id: int,
        *,
        headers: dict[str, str] | None = None,
        **kwargs,
    ) -> httpx.Response:
        token = await self.installation_token(installation_id)
        request_headers = {
            **self._base_headers(),
            **(headers or {}),
            "Authorization": f"token {token}",
        }
        response = await self._http.request(
            method, self._url(path), headers=request_headers, **kwargs
        )
        if response.status_code == 401:
            # Installation tokens can be revoked/expire early. Retry exactly once.
            token = await self.installation_token(installation_id, force=True)
            request_headers["Authorization"] = f"token {token}"
            response = await self._http.request(
                method, self._url(path), headers=request_headers, **kwargs
            )
        return response

    async def get_pull_request_diff(
        self, installation_id: int, owner: str, repo: str, pr_number: int
    ) -> str:
        response = await self._repo_request(
            "GET",
            f"/repos/{owner}/{repo}/pulls/{pr_number}",
            installation_id,
            headers={"Accept": "application/vnd.github.v3.diff"},
        )
        if response.status_code >= 400:
            raise GitHubAPIError(response.status_code, _safe_message(response))
        return response.text

    async def download_tarball(
        self, installation_id: int, owner: str, repo: str, ref: str
    ) -> bytes:
        response = await self._repo_request(
            "GET",
            f"/repos/{owner}/{repo}/tarball/{ref}",
            installation_id,
        )
        if response.status_code >= 400:
            raise GitHubAPIError(response.status_code, _safe_message(response))
        content = response.content
        limit = self._settings.max_repo_tarball_bytes
        if len(content) > limit:
            raise GitHubAPIError(413, f"repository tarball exceeds {limit} bytes")
        return content

    async def post_comment(
        self, installation_id: int, owner: str, repo: str, pr_number: int, body: str
    ) -> PostedComment:
        response = await self._repo_request(
            "POST",
            f"/repos/{owner}/{repo}/issues/{pr_number}/comments",
            installation_id,
            json={"body": body},
        )
        if response.status_code >= 400:
            raise GitHubAPIError(response.status_code, _safe_message(response))
        data = response.json()
        if "id" not in data or "html_url" not in data:
            raise GitHubAPIError(502, "comment response missing id/html_url")
        return PostedComment(id=int(data["id"]), html_url=str(data["html_url"]))


def _safe_message(response: httpx.Response) -> str:
    try:
        data = response.json()
        message = str(data.get("message", "unknown error")) if isinstance(data, dict) else str(data)
    except ValueError:
        message = response.text[:300] or "unknown error"
    # Guard against accidentally surfacing credentials from custom proxies.
    return message.replace("\n", " ")[:500]
