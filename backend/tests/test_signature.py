import pytest

from app.webhooks.signature import sign_payload, verify_signature

SECRET = "s3cret"
BODY = b'{"hello":"world"}'


def test_valid_signature() -> None:
    assert verify_signature(BODY, sign_payload(BODY, SECRET), SECRET) is True


def test_signature_is_case_insensitive_for_hex() -> None:
    header = sign_payload(BODY, SECRET)
    assert verify_signature(BODY, header.upper().replace("SHA256=", "sha256="), SECRET) is True


@pytest.mark.parametrize(
    "header",
    [
        None,
        "",
        "sha256=",
        "sha256=" + "a" * 63,
        "sha256=" + "z" * 64,
        "sha1=" + "a" * 40,
        "deadbeef",
    ],
)
def test_malformed_headers_are_rejected(header: str | None) -> None:
    assert verify_signature(BODY, header, SECRET) is False


def test_wrong_secret_is_rejected() -> None:
    assert verify_signature(BODY, sign_payload(BODY, "wrong"), SECRET) is False


def test_tampered_body_is_rejected() -> None:
    header = sign_payload(BODY, SECRET)
    assert verify_signature(BODY + b" ", header, SECRET) is False


def test_empty_secret_or_body_is_rejected() -> None:
    assert verify_signature(BODY, sign_payload(BODY, SECRET), "") is False
    assert verify_signature(b"", sign_payload(b"", SECRET), SECRET) is False
