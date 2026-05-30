"""FEMA OpenFEMA integration — disaster declarations and public assistance grants."""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

from echo.core.logger import get_logger

log = get_logger("echo.integrations.fema")

BASE_URL = "https://www.fema.gov/api/open/v2"


def _get(endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"{BASE_URL}/{endpoint.lstrip('/')}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_disaster_declarations(
    *,
    state: str | None = None,
    disaster_type: str | None = None,
    limit: int = 25,
    days_back: int | None = None,
) -> list[dict[str, Any]]:
    """Fetch recent FEMA disaster declarations.

    Args:
        state: Two-letter state abbreviation (e.g., "TX")
        disaster_type: "DR" for major disaster, "EM" for emergency, "FM" for fire management
        limit: Max records to return
        days_back: Filter to declarations from the last N days
    """
    params: dict[str, Any] = {"$top": limit, "$orderby": "declarationDate desc"}

    filters = []
    if state:
        filters.append(f"state eq '{state}'")
    if disaster_type:
        filters.append(f"incidentType eq '{disaster_type}'")
    if days_back:
        from datetime import datetime, timedelta, timezone
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%dT00:00:00.000Z")
        filters.append(f"declarationDate ge '{cutoff}'")
    if filters:
        params["$filter"] = " and ".join(filters)

    try:
        data = _get("DisasterDeclarationsSummaries", params)
        records = data.get("DisasterDeclarationsSummaries", [])
        log.info("FEMA disaster query returned %d records", len(records))
        return records
    except Exception as exc:
        log.exception("FEMA get_disaster_declarations failed: %s", exc)
        return []


def get_public_assistance_applicants(
    disaster_number: int,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Fetch public assistance applicants for a specific disaster number."""
    params = {
        "$filter": f"disasterNumber eq {disaster_number}",
        "$top": limit,
    }
    try:
        data = _get("PublicAssistanceApplicants", params)
        return data.get("PublicAssistanceApplicants", [])
    except Exception as exc:
        log.exception("FEMA get_public_assistance_applicants failed disaster=%s: %s",
                      disaster_number, exc)
        return []


def get_hazard_mitigation_grants(
    *,
    state: str | None = None,
    limit: int = 25,
) -> list[dict[str, Any]]:
    """Fetch FEMA hazard mitigation grant program data."""
    params: dict[str, Any] = {"$top": limit, "$orderby": "declarationDate desc"}
    if state:
        params["$filter"] = f"state eq '{state}'"
    try:
        data = _get("HazardMitigationGrants", params)
        return data.get("HazardMitigationGrants", [])
    except Exception as exc:
        log.exception("FEMA get_hazard_mitigation_grants failed: %s", exc)
        return []
