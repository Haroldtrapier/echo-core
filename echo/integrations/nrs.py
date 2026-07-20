"""NRS (National Response System) disaster-declaration adapter.

Mirrors the FEMA adapter's ``get_disaster_declarations(...)`` shape so the GovCon
pack can consume NRS the same way it consumes FEMA. NRS is a *provisioned* feed:
it makes a live call only when ``NRS_API_URL`` is configured. With no URL set the
adapter returns ``[]`` (a safe no-op), matching the project convention that a
missing credential degrades to empty rather than failing — so local build/test
never needs the feed.

Records are normalized into the FEMA-compatible shape used by the packs:

    {
        "source": "nrs",
        "incidentType": ...,
        "state": ...,
        "declarationTitle": ...,
        "declarationDate": ...,
        "declarationNumber": ...,
        "raw": <original record>,
    }

Point ``NRS_API_URL`` at any JSON endpoint that returns either a list of records
or ``{"results"|"data"|"declarations": [...]}``. Field mapping is best-effort and
tolerant of the common naming variants.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

from echo.config import NRS_API_KEY, NRS_API_URL
from echo.core.logger import get_logger

log = get_logger("echo.integrations.nrs")

SOURCE = "nrs"

# Candidate source keys → normalized field. First present key wins.
_FIELD_MAP: dict[str, tuple[str, ...]] = {
    "incidentType": ("incidentType", "incident_type", "type", "category"),
    "state": ("state", "stateCode", "state_abbr", "region"),
    "declarationTitle": ("declarationTitle", "title", "name", "description"),
    "declarationDate": ("declarationDate", "declaration_date", "date", "declaredAt"),
    "declarationNumber": ("declarationNumber", "declaration_number", "number", "id"),
}


def configured() -> bool:
    """True when a live NRS endpoint is provisioned."""
    return bool(NRS_API_URL)


def _extract_records(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        for key in ("results", "data", "declarations", "items", "records"):
            val = data.get(key)
            if isinstance(val, list):
                return [r for r in val if isinstance(r, dict)]
    return []


def normalize(record: dict[str, Any]) -> dict[str, Any]:
    """Map a raw NRS record into the FEMA-compatible declaration shape."""
    out: dict[str, Any] = {"source": SOURCE, "raw": record}
    for target, candidates in _FIELD_MAP.items():
        for key in candidates:
            if record.get(key) not in (None, ""):
                out[target] = record[key]
                break
    return out


def get_disaster_declarations(
    *,
    state: str | None = None,
    disaster_type: str | None = None,
    limit: int = 25,
    days_back: int | None = None,
) -> list[dict[str, Any]]:
    """Fetch recent NRS disaster declarations, normalized to the FEMA shape.

    Returns ``[]`` when ``NRS_API_URL`` is unset or on any error — the caller
    (``pack.safe_disaster_declarations``) treats an empty list as "no signals".
    """
    if not configured():
        return []

    params: dict[str, Any] = {"limit": limit}
    if state:
        params["state"] = state
    if disaster_type:
        params["type"] = disaster_type
    if days_back:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")
        params["since"] = cutoff

    url = NRS_API_URL
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)

    headers = {"Accept": "application/json"}
    if NRS_API_KEY:
        headers["Authorization"] = f"Bearer {NRS_API_KEY}"

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        records = _extract_records(data)
        log.info("NRS disaster query returned %d records", len(records))
        return [normalize(r) for r in records][:limit]
    except Exception as exc:  # noqa: BLE001
        log.exception("NRS get_disaster_declarations failed: %s", exc)
        return []
