"""GA4 (Google Analytics 4) integration — read campaign click/conversion data.

Echo tags every CTA with UTM parameters (see ``modules.content_store``), so GA4
can attribute traffic and conversions back to the post/campaign that drove them.
This is the data source that lets the Weekly Report answer "which post/CTA drove
clicks?".

Credentials (all optional — absent ⇒ graceful empty results):
  * ``GA4_PROPERTY_ID``  — numeric GA4 property id.
  * ``GA4_ACCESS_TOKEN`` — an OAuth2 bearer token for the Analytics Data API.
    (In production this is minted/refreshed from a service account by an
    external token provider; Echo just consumes it. Read-only.)

Without both, ``get_campaign_metrics`` returns ``{}`` and the caller degrades
to DB-only counts — never a crash, never fabricated numbers.
"""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

from echo.config import GA4_ACCESS_TOKEN, GA4_PROPERTY_ID
from echo.core.logger import get_logger

log = get_logger("echo.integrations.ga4")

_DATA_API = "https://analyticsdata.googleapis.com/v1beta"


def is_configured() -> bool:
    return bool(GA4_PROPERTY_ID and GA4_ACCESS_TOKEN)


def _run_report(body: dict[str, Any]) -> dict[str, Any]:
    url = f"{_DATA_API}/properties/{GA4_PROPERTY_ID}:runReport"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {GA4_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_campaign_metrics(
    campaigns: list[str] | None = None,
    *,
    days_back: int = 30,
) -> dict[str, dict[str, float]]:
    """Return per-campaign engagement keyed by UTM campaign name.

    Shape: ``{campaign: {"sessions": n, "active_users": n, "conversions": n}}``.
    Returns ``{}`` when GA4 is not configured or the call fails.
    """
    if not is_configured():
        log.warning("GA4 not configured (GA4_PROPERTY_ID/GA4_ACCESS_TOKEN) — returning {}")
        return {}

    start = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")
    body: dict[str, Any] = {
        "dateRanges": [{"startDate": start, "endDate": "today"}],
        "dimensions": [{"name": "sessionCampaignName"}],
        "metrics": [
            {"name": "sessions"},
            {"name": "activeUsers"},
            {"name": "conversions"},
        ],
        "limit": 250,
    }
    # Filter to specific campaigns when provided.
    if campaigns:
        body["dimensionFilter"] = {
            "filter": {
                "fieldName": "sessionCampaignName",
                "inListFilter": {"values": campaigns},
            }
        }

    try:
        report = _run_report(body)
    except Exception as exc:  # noqa: BLE001
        log.exception("GA4 runReport failed: %s", exc)
        return {}

    out: dict[str, dict[str, float]] = {}
    for row in report.get("rows", []):
        name = row.get("dimensionValues", [{}])[0].get("value", "(not set)")
        vals = [m.get("value", "0") for m in row.get("metricValues", [])]
        sessions = float(vals[0]) if len(vals) > 0 else 0.0
        active_users = float(vals[1]) if len(vals) > 1 else 0.0
        conversions = float(vals[2]) if len(vals) > 2 else 0.0
        out[name] = {
            "sessions": sessions,
            "active_users": active_users,
            "conversions": conversions,
        }
    log.info("GA4 returned metrics for %d campaign(s)", len(out))
    return out
