"""SEMA (State Emergency Management Agency) disaster-procurement adapter (Phase 2 stub).

Same provider interface + safe fallback as ``echo.integrations.nrs``:
  * configured (``SEMA_API_URL`` set) → live fetch (errors degrade to ``[]``)
  * ``SEMA_USE_MOCK=true``            → clearly-labelled mock signals (demo/dev)
  * otherwise                        → ``[]``

No live credentials required for build/test. TODO: implement `_fetch_live`
against the real state feed(s) when provisioned.
"""
from __future__ import annotations

import json
import urllib.request
from typing import Any

from echo.config import SEMA_API_KEY, SEMA_API_URL, SEMA_USE_MOCK
from echo.core.logger import get_logger

log = get_logger("echo.integrations.sema")

PROVIDER = "sema"


def is_configured() -> bool:
    return bool(SEMA_API_URL)


def mock_signals(*, state: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
    rows = [
        {
            "provider": PROVIDER,
            "mock": True,
            "signal_type": "state_rfq",
            "title": "[MOCK] State EM RFQ — bottled water & sheltering supplies",
            "state": state or "LA",
            "action": "Respond via state EM procurement portal; verify state vendor registration.",
        },
    ]
    return rows[:limit]


def _fetch_live(*, state: str | None, limit: int) -> list[dict[str, Any]]:
    params = {"limit": limit}
    if state:
        params["state"] = state
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{SEMA_API_URL.rstrip('/')}/rfqs?{qs}"
    headers = {"Accept": "application/json"}
    if SEMA_API_KEY:
        headers["Authorization"] = f"Bearer {SEMA_API_KEY}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    signals = data.get("signals", data if isinstance(data, list) else [])
    for s in signals:
        s.setdefault("provider", PROVIDER)
    return signals[:limit]


def get_procurement_signals(*, state: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
    """Return SEMA procurement signals. Never raises."""
    if is_configured():
        try:
            return _fetch_live(state=state, limit=limit)
        except Exception as exc:  # noqa: BLE001
            log.info("SEMA live fetch failed (%s) — returning no signals", exc)
            return []
    if SEMA_USE_MOCK:
        return mock_signals(state=state, limit=limit)
    return []
