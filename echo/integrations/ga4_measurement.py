"""GA4 Measurement Protocol — outbound conversion events (Phase 2).

Distinct from ``integrations.ga4`` (read-only attribution). This SENDS events
(CTA clicks, Sturgeon handoffs) to GA4 for conversion tracking.

Credentials (both required; absent ⇒ no-op, never a crash):
  * ``GA4_MEASUREMENT_ID`` — e.g. ``G-XXXXXXX``
  * ``GA4_API_SECRET``     — Measurement Protocol API secret

When unconfigured, :func:`send_event` returns ``{"sent": False,
"reason": "not_configured"}`` and makes no network call.
"""
from __future__ import annotations

import json
import urllib.request
from typing import Any

from echo.config import GA4_API_SECRET, GA4_MEASUREMENT_ID
from echo.core.logger import get_logger

log = get_logger("echo.integrations.ga4_measurement")

_MP_ENDPOINT = "https://www.google-analytics.com/mp/collect"


def is_configured() -> bool:
    return bool(GA4_MEASUREMENT_ID and GA4_API_SECRET)


def send_event(
    *,
    client_id: str,
    name: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Send one GA4 event. No-op (no network) when unconfigured."""
    if not is_configured():
        return {"sent": False, "reason": "not_configured"}

    payload = {
        "client_id": client_id or "echo.server",
        "events": [{"name": name, "params": params or {}}],
    }
    url = f"{_MP_ENDPOINT}?measurement_id={GA4_MEASUREMENT_ID}&api_secret={GA4_API_SECRET}"
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            ok = 200 <= resp.status < 300
        return {"sent": ok, "status": getattr(resp, "status", None)}
    except Exception as exc:  # noqa: BLE001 — tracking must never break the caller
        log.warning("GA4 MP send failed for %s: %s", name, exc)
        return {"sent": False, "reason": "error", "error": str(exc)}
