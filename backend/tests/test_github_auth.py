import jwt
import pytest
from cryptography.hazmat.primitives import serialization

from app.github.auth import build_app_jwt
from app.github.errors import GitHubAuthError


def public_key_from(private_key_pem: str):
    return serialization.load_pem_private_key(private_key_pem.encode(), password=None).public_key()


def test_jwt_contains_expected_claims(private_key_pem: str) -> None:
    token = build_app_jwt("12345", private_key_pem, now=1_700_000_000)
    payload = jwt.decode(
        token,
        public_key_from(private_key_pem),
        algorithms=["RS256"],
        options={"verify_exp": False, "verify_iat": False},
    )
    assert payload["iss"] == "12345"
    assert payload["iat"] == 1_700_000_000 - 60
    assert payload["exp"] == 1_700_000_000 + 540


def test_non_numeric_app_id_stays_a_string(private_key_pem: str) -> None:
    token = build_app_jwt("app-slug", private_key_pem, now=1_700_000_000)
    payload = jwt.decode(
        token,
        public_key_from(private_key_pem),
        algorithms=["RS256"],
        options={"verify_exp": False, "verify_iat": False},
    )
    assert payload["iss"] == "app-slug"


def test_missing_app_id_rejected(private_key_pem: str) -> None:
    with pytest.raises(GitHubAuthError, match="GITHUB_APP_ID"):
        build_app_jwt("", private_key_pem)


def test_missing_private_key_rejected() -> None:
    with pytest.raises(GitHubAuthError, match="private key"):
        build_app_jwt("123", None)


def test_malformed_private_key_rejected() -> None:
    with pytest.raises(GitHubAuthError, match="private key"):
        build_app_jwt("123", "not-a-pem")
