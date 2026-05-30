"""USASpending.gov integration — federal awards and spending data."""
from __future__ import annotations

import json
import urllib.request
from typing import Any

from echo.core.logger import get_logger

log = get_logger("echo.integrations.usaspending")

BASE_URL = "https://api.usaspending.gov/api/v2"


def _post(endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = f"{BASE_URL}/{endpoint.lstrip('/')}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def search_awards(
    keywords: list[str],
    *,
    award_type_codes: list[str] | None = None,
    limit: int = 10,
    page: int = 1,
) -> dict[str, Any]:
    """Full-text keyword search across federal awards.

    award_type_codes: e.g. ["A", "B", "C", "D"] for contracts,
    ["02", "03", "04", "05"] for grants.
    """
    payload: dict[str, Any] = {
        "filters": {
            "keywords": keywords,
        },
        "fields": [
            "Award ID", "Recipient Name", "Award Amount",
            "Total Outlays", "Description", "Start Date", "End Date",
            "Awarding Agency", "Awarding Sub Agency", "Award Type",
            "Contract Award Type", "NAICS Code",
        ],
        "page": page,
        "limit": limit,
        "sort": "Award Amount",
        "order": "desc",
    }
    if award_type_codes:
        payload["filters"]["award_type_codes"] = award_type_codes

    try:
        result = _post("search/spending_by_award/", payload)
        log.info("USASpending award search keywords=%r returned %d results",
                 keywords, len(result.get("results", [])))
        return result
    except Exception as exc:
        log.exception("USASpending search_awards failed: %s", exc)
        return {"results": [], "page_metadata": {}}


def get_agency_spending(
    agency_id: str,
    fiscal_year: int,
) -> dict[str, Any]:
    """Get total spending breakdown for a federal agency in a given fiscal year."""
    try:
        result = _post("agency/awards/count/", {
            "filters": {
                "agency": agency_id,
                "fiscal_year": fiscal_year,
            }
        })
        return result
    except Exception as exc:
        log.exception("USASpending get_agency_spending failed agency=%s fy=%s: %s",
                      agency_id, fiscal_year, exc)
        return {}


def get_recipient_awards(
    recipient_name: str,
    *,
    fiscal_year: int | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Fetch awards for a specific recipient by name."""
    filters: dict[str, Any] = {"recipient_search_text": [recipient_name]}
    if fiscal_year:
        filters["time_period"] = [{"start_date": f"{fiscal_year}-10-01",
                                    "end_date": f"{fiscal_year + 1}-09-30"}]
    try:
        result = _post("search/spending_by_award/", {
            "filters": filters,
            "fields": ["Award ID", "Recipient Name", "Award Amount",
                       "Awarding Agency", "Start Date", "End Date"],
            "limit": limit,
            "sort": "Award Amount",
            "order": "desc",
        })
        return result.get("results", [])
    except Exception as exc:
        log.exception("USASpending get_recipient_awards failed recipient=%r: %s",
                      recipient_name, exc)
        return []
