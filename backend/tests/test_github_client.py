import httpx
import pytest

from app.github.client import GitHubClient
from app.github.errors import GitHubAPIError, GitHubAuthError
from app.settings import Settings

API = "https://api.github.test"


def make_settings(private_key_pem: str, **overrides) -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        github_api_url=API,
        github_app_id="12345",
        github_private_key_pem=private_key_pem,
        worker_enabled=False,
        **overrides,
    )


def token_response() -> httpx.Response:
    return httpx.Response(
        201,
        json={"token": "ghs_test", "expires_at": "2099-01-01T00:00:00Z"},
    )


async def test_installation_token_and_cache(private_key_pem: str) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.url.path == "/app/installations/99/access_tokens"
        assert request.headers["authorization"].startswith("Bearer ey")
        assert request.headers["x-github-api-version"] == "2022-11-28"
        return token_response()

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = GitHubClient(make_settings(private_key_pem), http=http)
        assert await client.installation_token(99) == "ghs_test"
        assert await client.installation_token(99) == "ghs_test"
    assert len(calls) == 1
    await client.aclose()


async def test_token_endpoint_error_is_normalized(private_key_pem: str) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "Integration not found"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = GitHubClient(make_settings(private_key_pem), http=http)
        with pytest.raises(GitHubAPIError, match="Integration not found") as exc:
            await client.installation_token(99)
    assert exc.value.status_code == 403


async def test_token_response_missing_fields(private_key_pem: str) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"token": "x"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = GitHubClient(make_settings(private_key_pem), http=http)
        with pytest.raises(GitHubAuthError, match="expires_at"):
            await client.installation_token(99)


async def test_diff_request_uses_diff_accept_header(private_key_pem: str) -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/access_tokens"):
            return token_response()
        seen["accept"] = request.headers["accept"]
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(200, text="diff --git a/x b/x\n+hello")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = GitHubClient(make_settings(private_key_pem), http=http)
        diff = await client.get_pull_request_diff(99, "acme", "demo", 7)
    assert diff.startswith("diff --git")
    assert seen["accept"] == "application/vnd.github.v3.diff"
    assert seen["auth"] == "token ghs_test"


async def test_expired_token_is_refreshed_once_after_401(private_key_pem: str) -> None:
    token_calls = 0
    comment_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls, comment_calls
        if request.url.path.endswith("/access_tokens"):
            token_calls += 1
            return httpx.Response(
                201,
                json={
                    "token": "old" if token_calls == 1 else "new",
                    "expires_at": "2099-01-01T00:00:00Z",
                },
            )
        comment_calls += 1
        if request.headers["authorization"] == "token old":
            return httpx.Response(401, json={"message": "Bad credentials"})
        return httpx.Response(201, json={"id": 5, "html_url": "https://github.com/c/5"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = GitHubClient(make_settings(private_key_pem), http=http)
        comment = await client.post_comment(99, "acme", "demo", 7, "hello")
    assert comment.id == 5
    assert comment.html_url.endswith("/5")
    assert token_calls == 2
    assert comment_calls == 2


async def test_post_comment_body(private_key_pem: str) -> None:
    bodies: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/access_tokens"):
            return token_response()
        bodies.append(request.content)
        return httpx.Response(201, json={"id": 9, "html_url": "https://github.com/c/9"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = GitHubClient(make_settings(private_key_pem), http=http)
        await client.post_comment(99, "acme", "demo", 7, "## Report")
    assert b'{"body":"## Report"}' in bodies[0]


async def test_post_comment_validation_error(private_key_pem: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/access_tokens"):
            return token_response()
        return httpx.Response(422, json={"message": "Validation Failed"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = GitHubClient(make_settings(private_key_pem), http=http)
        with pytest.raises(GitHubAPIError, match="Validation Failed") as exc:
            await client.post_comment(99, "acme", "demo", 7, "x")
    assert exc.value.status_code == 422


async def test_post_comment_missing_fields(private_key_pem: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/access_tokens"):
            return token_response()
        return httpx.Response(201, json={"id": 1})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = GitHubClient(make_settings(private_key_pem), http=http)
        with pytest.raises(GitHubAPIError, match="missing id/html_url"):
            await client.post_comment(99, "acme", "demo", 7, "x")


async def test_tarball_success_and_size_limit(private_key_pem: str) -> None:
    payload = b"x" * 100

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/access_tokens"):
            return token_response()
        return httpx.Response(200, content=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = GitHubClient(make_settings(private_key_pem), http=http)
        assert await client.download_tarball(99, "acme", "demo", "abc") == payload
        client._settings.max_repo_tarball_bytes = 10
        with pytest.raises(GitHubAPIError) as exc:
            await client.download_tarball(99, "acme", "demo", "abc")
    assert exc.value.status_code == 413


async def test_tarball_api_error(private_key_pem: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/access_tokens"):
            return token_response()
        return httpx.Response(404, text="Not Found")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = GitHubClient(make_settings(private_key_pem), http=http)
        with pytest.raises(GitHubAPIError, match="Not Found"):
            await client.download_tarball(99, "acme", "demo", "abc")


async def test_client_context_manager_and_owned_http(private_key_pem: str) -> None:
    # No request is made; this checks the context manager closes the owned client.
    client = GitHubClient(make_settings(private_key_pem))
    async with client as entered:
        assert entered is client
    assert client._http.is_closed
