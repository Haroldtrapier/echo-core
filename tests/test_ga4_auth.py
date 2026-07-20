"""GA4 service-account token minting (echo.integrations.ga4_auth).

Proves Echo can mint its own read-only GA4 token from a service account instead
of depending on an external refresher. Network-free: a throwaway RSA key stands
in for a real service account and the token exchange is monkeypatched, so the
assertion's RS256 signature is verified locally against the public key.
"""
from __future__ import annotations

import base64
import json
import time

import pytest

from echo.integrations import ga4_auth as ga

# The signing path needs `cryptography` (a declared dependency).
crypto = pytest.importorskip("cryptography")
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import padding, rsa  # noqa: E402


def _service_account() -> tuple[dict, "rsa.RSAPrivateKey"]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    info = {
        "client_email": "echo@proj.iam.gserviceaccount.com",
        "private_key": pem,
        "private_key_id": "kid123",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    return info, key


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


@pytest.fixture(autouse=True)
def _clear(monkeypatch):
    monkeypatch.setattr(ga, "GA4_SERVICE_ACCOUNT_JSON", "", raising=False)
    monkeypatch.setattr(ga, "GA4_SERVICE_ACCOUNT_FILE", "", raising=False)
    monkeypatch.setattr(ga, "GA4_ACCESS_TOKEN", "", raising=False)
    ga.reset_cache()
    yield
    ga.reset_cache()


def test_assertion_is_valid_rs256(monkeypatch):
    info, key = _service_account()
    monkeypatch.setattr(ga, "GA4_SERVICE_ACCOUNT_JSON", json.dumps(info))
    assert ga.service_account_configured() is True

    now = int(time.time())
    assertion = ga._build_assertion(info, now)
    h_b64, c_b64, s_b64 = assertion.split(".")

    header = json.loads(_unb64(h_b64))
    claims = json.loads(_unb64(c_b64))
    assert header == {"alg": "RS256", "typ": "JWT", "kid": "kid123"}
    assert claims["scope"] == ga._SCOPE
    assert claims["iss"] == info["client_email"]
    assert claims["exp"] - claims["iat"] == 3600

    # The signature must verify against the service account's public key — this
    # is exactly what Google's token endpoint checks.
    key.public_key().verify(
        _unb64(s_b64), f"{h_b64}.{c_b64}".encode(), padding.PKCS1v15(), hashes.SHA256()
    )


def test_mint_and_cache(monkeypatch):
    info, _ = _service_account()
    monkeypatch.setattr(ga, "GA4_SERVICE_ACCOUNT_JSON", json.dumps(info))

    calls = {"n": 0}

    def fake_exchange(assertion, token_uri):
        calls["n"] += 1
        assert token_uri == info["token_uri"]
        return (f"ya29.MINTED{calls['n']}", time.time() + 3600)

    monkeypatch.setattr(ga, "_exchange", fake_exchange)

    tok1 = ga.get_access_token()
    tok2 = ga.get_access_token()            # served from cache — no second exchange
    assert tok1 == "ya29.MINTED1"
    assert tok2 == tok1
    assert calls["n"] == 1

    tok3 = ga.get_access_token(force_refresh=True)  # forces a fresh mint
    assert tok3 == "ya29.MINTED2"
    assert calls["n"] == 2


def test_expired_cache_triggers_refresh(monkeypatch):
    info, _ = _service_account()
    monkeypatch.setattr(ga, "GA4_SERVICE_ACCOUNT_JSON", json.dumps(info))
    # Prime the cache with an already-expired token.
    ga._cache = ("stale", time.time() - 1)

    monkeypatch.setattr(ga, "_exchange", lambda a, u: ("fresh", time.time() + 3600))
    assert ga.get_access_token() == "fresh"


def test_falls_back_to_static_token(monkeypatch):
    # No service account, but a pre-minted token is present.
    monkeypatch.setattr(ga, "GA4_ACCESS_TOKEN", "static-token")
    assert ga.service_account_configured() is False
    assert ga.get_access_token() == "static-token"


def test_returns_none_when_unconfigured():
    assert ga.get_access_token() is None


def test_invalid_service_account_json_is_ignored(monkeypatch):
    monkeypatch.setattr(ga, "GA4_SERVICE_ACCOUNT_JSON", "{not valid json")
    assert ga.service_account_configured() is False
    assert ga.get_access_token() is None
