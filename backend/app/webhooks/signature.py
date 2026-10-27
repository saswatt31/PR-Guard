"""HMAC verification for GitHub webhooks."""

from __future__ import annotations

import hashlib
import hmac

PREFIX = "sha256="


def verify_signature(payload: bytes, signature_header: str | None, secret: str) -> bool:
    """Constant-time verification of ``X-Hub-Signature-256``.

    The raw request body must be used byte-for-byte; re-serializing JSON breaks the
    signature. Returns False for missing/malformed headers rather than raising so the
    caller can return a uniform 401.
    """

    if not payload or not signature_header or not secret:
        return False
    if not signature_header.startswith(PREFIX):
        return False
    supplied = signature_header[len(PREFIX) :]
    if len(supplied) != 64:
        return False
    expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, supplied.lower())


def sign_payload(payload: bytes, secret: str) -> str:
    """Produce a valid header. Used by tests and local webhook replay."""

    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return f"{PREFIX}{digest}"
