"""GitHub App JWT creation.

GitHub requires a short-lived RS256 JWT signed with the App private key. Installation
tokens (created in client.py) are what actually authorize repository operations.
"""

from __future__ import annotations

from datetime import UTC, datetime

import jwt

from app.github.errors import GitHubAuthError


def build_app_jwt(app_id: str, private_key: str | None, *, now: int | None = None) -> str:
    if not app_id:
        raise GitHubAuthError("GITHUB_APP_ID is not configured")
    if not private_key:
        raise GitHubAuthError("GitHub App private key is not configured")
    issued_at = now if now is not None else int(datetime.now(UTC).timestamp())
    # Backdate iat to tolerate clock skew; GitHub rejects tokens older than 10 minutes.
    payload = {
        "iat": issued_at - 60,
        "exp": issued_at + 540,
        # PyJWT requires a string issuer; GitHub accepts the App id as a string.
        "iss": str(app_id),
    }
    try:
        return jwt.encode(payload, private_key, algorithm="RS256")
    except Exception as exc:  # noqa: BLE001 - normalize cryptography errors for callers
        raise GitHubAuthError("could not sign GitHub App JWT; check the private key") from exc
