"""Echo Core authentication middleware.

All non-health endpoints require either:
  - Header:  x-echo-key: <ECHO_API_KEY>
  - Header:  Authorization: Bearer <ECHO_API_KEY>

If ECHO_API_KEY is not set, authentication is disabled (dev mode warning printed).
"""
from __future__ import annotations

from fastapi import Header, HTTPException, Security
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from echo.config import ECHO_API_KEY
from echo.core.logger import get_logger

log = get_logger("echo.auth")

_api_key_header = APIKeyHeader(name="x-echo-key", auto_error=False)
_bearer_scheme = HTTPBearer(auto_error=False)


def require_api_key(
    x_echo_key: str | None = Security(_api_key_header),
    bearer: HTTPAuthorizationCredentials | None = Security(_bearer_scheme),
) -> str:
    """FastAPI dependency — validates API key. Raises 401 on failure."""
    if not ECHO_API_KEY:
        log.warning("ECHO_API_KEY is not set — authentication disabled (dev mode)")
        return "dev"

    token: str | None = None
    if x_echo_key:
        token = x_echo_key
    elif bearer:
        token = bearer.credentials

    if not token or token != ECHO_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

    return token
