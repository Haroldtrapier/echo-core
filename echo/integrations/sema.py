"""SEMA (State Emergency Management Agency) disaster-declaration adapter.

State emergency-management agencies publish their own declarations/alerts ahead
of (or alongside) federal FEMA declarations. This adapter mirrors the FEMA
adapter's ``get_disaster_declarations(...)`` shape so the GovCon pack can fold
state signals into the same brief/alert.

Like ``nrs``, SEMA is a *provisioned* feed: it calls out only when
``SEMA_API_URL`` is configured, and returns ``[]`` otherwise (safe no-op). The
URL may contain a ``{state}`` placeholder, which is filled from the ``state``
argument so a single template can serve many state portals, e.g.::

    SEMA_API_URL=https://alerts.example.gov/{state}/declarations.json

Records are normalized to the FEMA-compatible shape (``source="sema"``).
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

from echo.config import SEMA_API_KEY, SEMA_API_URL
from echo.core.logger import get_logger

log = get_logger("echo.integrations.sema")

SOURCE = "sema"

_FIELD_MAP: dict[str, tuple[str, ...]] = {
    "incidentType": ("incidentType", "incident_type", "type", "hazard", "category"),
    "state": ("state", "stateCode", "state_abbr", "jurisdiction"),
    "declarationTitle": ("declarationTitle", "title", "name", "headline", "description"),
    "declarationDate": ("declarationDate", "declaration_date", "date", "issued", "updated"),
    "declarationNumber": ("declarationNumber", "declaration_number", "number", "id"),
}


def configured() -> bool:
    """True when a live SEMA endpoint is provisioned."""
    return bool(SEMA_API_URL)


def _extract_records(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        for key in ("results", "data", "declarations", "alerts", "items", "features"):
            val = data.get(key)
            if isinstance(val, list):
                # GeoJSON-style {"features": [{"properties": {...}}]} support.
                out = []
                for r in val:
                    if isinstance(r, dict):
                        out.append(r.get("properties") if isinstance(r.get("properties"), dict) else r)
                return [r for r in out if isinstance(r, dict)]
    return []


def normalize(record: dict[str, Any], *, state: str | None = None) -> dict[str, Any]:
    """Map a raw SEMA record into the FEMA-compatible declaration shape."""
    out: dict[str, Any] = {"source": SOURCE, "raw": record}
    for target, candidates in _FIELD_MAP.items():
        for key in candidates:
            if record.get(key) not in (None, ""):
                out[target] = record[key]
                break
    if "state" not in out and state:
        out["state"] = state
    return out


def get_disaster_declarations(
    *,
    state: str | None = None,
    disaster_type: str | None = None,
    limit: int = 25,
    days_back: int | None = None,
) -> list[dict[str, Any]]:
    """Fetch recent SEMA declarations, normalized to the FEMA shape.

    Returns ``[]`` when ``SEMA_API_URL`` is unset or on any error.
    """
    if not configured():
        return []

    # Fill a {state} template if present; else pass state as a query param.
    url = SEMA_API_URL
    params: dict[str, Any] = {"limit": limit}
    if "{state}" in url:
        url = url.replace("{state}", urllib.parse.quote(state or ""))
    elif state:
        params["state"] = state
    if disaster_type:
        params["type"] = disaster_type
    if days_back:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")
        params["since"] = cutoff

    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)

    headers = {"Accept": "application/json"}
    if SEMA_API_KEY:
        headers["Authorization"] = f"Bearer {SEMA_API_KEY}"

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        records = _extract_records(data)
        log.info("SEMA disaster query returned %d records", len(records))
        return [normalize(r, state=state) for r in records][:limit]
    except Exception as exc:  # noqa: BLE001
        log.exception("SEMA get_disaster_declarations failed: %s", exc)
        return []
