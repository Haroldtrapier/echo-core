"""SAM.gov integration — search federal contract opportunities."""
from __future__ import annotations

import urllib.parse
import urllib.request
import json
from typing import Any

from echo.config import SAM_GOV_API_KEY
from echo.core.logger import get_logger

log = get_logger("echo.integrations.sam_gov")

BASE_URL = "https://api.sam.gov/opportunities/v2/search"


def search_opportunities(
    keywords: str,
    *,
    limit: int = 10,
    posted_from: str | None = None,
    posted_to: str | None = None,
    naics_code: str | None = None,
    set_aside: str | None = None,
) -> list[dict[str, Any]]:
    """Search SAM.gov for contract opportunities.

    Returns a list of opportunity dicts with keys:
    noticeId, title, solicitationNumber, postedDate, responseDeadLine,
    naicsCode, baseType, typeOfSetAside, description, uiLink
    """
    if not SAM_GOV_API_KEY:
        log.warning("SAM_GOV_API_KEY not set — returning empty opportunities")
        return []

    params: dict[str, Any] = {
        "api_key": SAM_GOV_API_KEY,
        "q": keywords,
        "limit": limit,
        "offset": 0,
    }
    if posted_from:
        params["postedFrom"] = posted_from
    if posted_to:
        params["postedTo"] = posted_to
    if naics_code:
        params["naicsCode"] = naics_code
    if set_aside:
        params["typeOfSetAside"] = set_aside

    url = f"{BASE_URL}?{urllib.parse.urlencode(params)}"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        opportunities = data.get("opportunitiesData", [])
        log.info("SAM.gov search keywords=%r returned %d results", keywords, len(opportunities))
        return opportunities
    except Exception as exc:
        log.exception("SAM.gov search failed: %s", exc)
        return []


def get_opportunity(notice_id: str) -> dict[str, Any] | None:
    """Fetch a single SAM.gov opportunity by noticeId."""
    if not SAM_GOV_API_KEY:
        return None
    url = f"https://api.sam.gov/opportunities/v2/search?api_key={SAM_GOV_API_KEY}&noticeid={notice_id}"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        opps = data.get("opportunitiesData", [])
        return opps[0] if opps else None
    except Exception as exc:
        log.exception("SAM.gov get_opportunity failed notice_id=%s: %s", notice_id, exc)
        return None
