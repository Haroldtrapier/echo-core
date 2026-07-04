"""NRS (National Readiness System) disaster-procurement adapter (Phase 2 stub).

Provider interface with a safe fallback:
  * configured (``NRS_API_URL`` set)  → live fetch (errors degrade to ``[]``)
  * ``NRS_USE_MOCK=true``             → clearly-labelled mock signals (demo/dev)
  * otherwise                         → ``[]`` (disabled, never a crash)

No live credentials are required for build/test. TODO: implement the real
`_fetch_live` against the NRS feed when it is provisioned.
"""
from __future__ import annotations

import json
import urllib.request
from typing import Any

from echo.config import NRS_API_KEY, NRS_API_URL, NRS_USE_MOCK
from echo.core.logger import get_logger

log = get_logger("echo.integrations.nrs")

PROVIDER = "nrs"


def is_configured() -> bool:
    return bool(NRS_API_URL)


def mock_signals(*, state: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
    rows = [
        {
            "provider": PROVIDER,
            "mock": True,
            "signal_type": "readiness_supply",
            "title": "[MOCK] Emergency generator + fuel logistics readiness gap",
            "state": state or "TX",
            "action": "Pre-position rapid-response supply capability for public assistance.",
        },
        {
            "provider": PROVIDER,
            "mock": True,
            "signal_type": "procurement_alert",
            "title": "[MOCK] Temporary housing / debris removal surge anticipated",
            "state": state or "FL",
            "action": "Confirm SAM.gov + disaster NAICS eligibility; line up teaming partners.",
        },
    ]
    return rows[:limit]


def _fetch_live(*, state: str | None, limit: int) -> list[dict[str, Any]]:
    params = {"limit": limit}
    if state:
        params["state"] = state
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{NRS_API_URL.rstrip('/')}/signals?{qs}"
    headers = {"Accept": "application/json"}
    if NRS_API_KEY:
        headers["Authorization"] = f"Bearer {NRS_API_KEY}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    signals = data.get("signals", data if isinstance(data, list) else [])
    for s in signals:
        s.setdefault("provider", PROVIDER)
    return signals[:limit]


def get_procurement_signals(*, state: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
    """Return NRS procurement/readiness signals. Never raises."""
    if is_configured():
        try:
            return _fetch_live(state=state, limit=limit)
        except Exception as exc:  # noqa: BLE001
            log.info("NRS live fetch failed (%s) — returning no signals", exc)
            return []
    if NRS_USE_MOCK:
        return mock_signals(state=state, limit=limit)
    return []
