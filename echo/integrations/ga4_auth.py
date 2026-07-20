"""Mint & cache GA4 Data API access tokens from a Google service account.

Removes the "run your own token refresher" burden noted in DEPLOY.md. When a
service account is configured (``GA4_SERVICE_ACCOUNT_JSON`` inline or
``GA4_SERVICE_ACCOUNT_FILE`` path), Echo signs a JWT with the service account's
RSA key, exchanges it at Google's OAuth token endpoint for a short-lived
read-only access token, and caches it in-process until shortly before expiry.

Resolution order for the token used by ``integrations.ga4``:
  1. A cached/minted service-account token (if a service account is configured).
  2. ``GA4_ACCESS_TOKEN`` (a pre-minted token from an external provider).
  3. ``None`` → GA4 stays "not configured" and callers degrade to DB-only counts.

Signing needs the ``cryptography`` package. If it is unavailable the minter logs
and returns ``None`` (never crashes) so the rest of Echo is unaffected.
"""
from __future__ import annotations

import base64
import json
import time
import urllib.parse
import urllib.request
from typing import Any

from echo.config import (
    GA4_ACCESS_TOKEN,
    GA4_SERVICE_ACCOUNT_FILE,
    GA4_SERVICE_ACCOUNT_JSON,
)
from echo.core.logger import get_logger

log = get_logger("echo.integrations.ga4_auth")

_TOKEN_URI = "https://oauth2.googleapis.com/token"
_SCOPE = "https://www.googleapis.com/auth/analytics.readonly"
_JWT_GRANT = "urn:ietf:params:oauth:grant-type:jwt-bearer"
# Refresh a bit before the real expiry so an in-flight request never uses a
# token that expires mid-call.
_EXPIRY_SKEW_SECONDS = 120

# In-process cache: (access_token, expires_at_epoch).
_cache: tuple[str, float] | None = None


def _b64url(raw: bytes) -> bytes:
    return base64.urlsafe_b64encode(raw).rstrip(b"=")


def _load_service_account() -> dict[str, Any] | None:
    """Load the service-account key from inline JSON or a file path, or None."""
    raw = GA4_SERVICE_ACCOUNT_JSON.strip()
    if not raw and GA4_SERVICE_ACCOUNT_FILE:
        try:
            with open(GA4_SERVICE_ACCOUNT_FILE, "r", encoding="utf-8") as fh:
                raw = fh.read()
        except OSError as exc:
            log.warning("GA4 service account file unreadable (%s): %s",
                        GA4_SERVICE_ACCOUNT_FILE, exc)
            return None
    if not raw:
        return None
    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.warning("GA4 service account JSON is invalid: %s", exc)
        return None
    if not info.get("client_email") or not info.get("private_key"):
        log.warning("GA4 service account missing client_email/private_key")
        return None
    return info


def service_account_configured() -> bool:
    return _load_service_account() is not None


def _sign_rs256(message: bytes, private_key_pem: str) -> bytes | None:
    """RS256 sign ``message`` with the PEM private key. None if crypto missing."""
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
    except Exception as exc:  # noqa: BLE001 — optional dependency
        log.warning("cryptography unavailable — cannot mint GA4 token (%s). "
                    "Install `cryptography` or set GA4_ACCESS_TOKEN.", exc)
        return None
    try:
        key = serialization.load_pem_private_key(private_key_pem.encode("utf-8"),
                                                 password=None)
        return key.sign(message, padding.PKCS1v15(), hashes.SHA256())
    except Exception as exc:  # noqa: BLE001
        log.exception("GA4 JWT signing failed: %s", exc)
        return None


def _build_assertion(info: dict[str, Any], now: int) -> str | None:
    """Build a signed JWT assertion for the token exchange, or None on failure."""
    header = {"alg": "RS256", "typ": "JWT"}
    if info.get("private_key_id"):
        header["kid"] = info["private_key_id"]
    claims = {
        "iss": info["client_email"],
        "scope": _SCOPE,
        "aud": info.get("token_uri", _TOKEN_URI),
        "iat": now,
        "exp": now + 3600,
    }
    signing_input = (
        _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
        + b"."
        + _b64url(json.dumps(claims, separators=(",", ":")).encode("utf-8"))
    )
    signature = _sign_rs256(signing_input, info["private_key"])
    if signature is None:
        return None
    return (signing_input + b"." + _b64url(signature)).decode("ascii")


def _exchange(assertion: str, token_uri: str) -> tuple[str, float] | None:
    """Exchange a JWT assertion for an access token; return (token, expires_at)."""
    data = urllib.parse.urlencode(
        {"grant_type": _JWT_GRANT, "assertion": assertion}
    ).encode("utf-8")
    req = urllib.request.Request(
        token_uri,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        log.exception("GA4 token exchange failed: %s", exc)
        return None
    token = payload.get("access_token")
    if not token:
        log.warning("GA4 token exchange returned no access_token")
        return None
    expires_in = int(payload.get("expires_in", 3600))
    return token, time.time() + expires_in


def _mint(now: int | None = None) -> tuple[str, float] | None:
    info = _load_service_account()
    if info is None:
        return None
    now = now if now is not None else int(time.time())
    assertion = _build_assertion(info, now)
    if assertion is None:
        return None
    return _exchange(assertion, info.get("token_uri", _TOKEN_URI))


def get_access_token(*, force_refresh: bool = False) -> str | None:
    """Return a valid GA4 access token, minting/refreshing as needed.

    Prefers a service-account-minted token (cached until near expiry); falls back
    to the static ``GA4_ACCESS_TOKEN``; returns ``None`` when neither is
    available. Never raises.
    """
    global _cache

    if not force_refresh and _cache is not None:
        token, expires_at = _cache
        if time.time() < expires_at - _EXPIRY_SKEW_SECONDS:
            return token

    minted = _mint()
    if minted is not None:
        _cache = minted
        log.info("Minted GA4 access token (valid ~%ds)",
                 int(minted[1] - time.time()))
        return minted[0]

    # No service account (or minting failed) — fall back to a static token.
    return GA4_ACCESS_TOKEN or None


def reset_cache() -> None:
    """Clear the cached token (test/rotation helper)."""
    global _cache
    _cache = None
