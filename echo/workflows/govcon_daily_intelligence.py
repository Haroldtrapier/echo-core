"""GovCon daily intelligence briefing workflow."""
from __future__ import annotations

from typing import Any

from echo.core.registry import register
from echo.core.workflow import BaseWorkflow, WorkflowResult
from echo.integrations import sam_gov, usaspending
from echo.modules.ai_generator import generate_intelligence_summary
from echo.modules.notifications import notify_slack


@register
class GovConDailyIntelligenceWorkflow(BaseWorkflow):
    slug = "govcon_daily_intelligence"
    name = "GovCon Daily Intelligence Briefing"
    description = (
        "Pulls the latest federal opportunities from SAM.gov and award data from USASpending, "
        "generates an AI-written intelligence briefing, and sends it to Slack."
    )

    def run(self, db: Any, payload: dict[str, Any]) -> WorkflowResult:
        keywords = payload.get("keywords", ["information technology", "cybersecurity", "cloud"])
        if isinstance(keywords, str):
            keywords = [keywords]

        # Fetch SAM.gov opportunities
        opportunities = sam_gov.search_opportunities(
            " ".join(keywords),
            limit=payload.get("sam_limit", 5),
            days_back=payload.get("days_back", 7),  # type: ignore[arg-type]
        )

        # Fetch USASpending recent awards
        awards_result = usaspending.search_awards(
            keywords,
            award_type_codes=payload.get("award_type_codes", ["A", "B", "C", "D"]),
            limit=payload.get("awards_limit", 5),
        )
        awards = awards_result.get("results", [])

        intel_data: dict[str, Any] = {
            "keywords": keywords,
            "sam_opportunities": [
                {
                    "title": o.get("title"),
                    "notice_id": o.get("noticeId"),
                    "posted": o.get("postedDate"),
                    "deadline": o.get("responseDeadLine"),
                    "naics": o.get("naicsCode"),
                }
                for o in opportunities[:5]
            ],
            "recent_awards": [
                {
                    "award_id": a.get("Award ID"),
                    "recipient": a.get("Recipient Name"),
                    "amount": a.get("Award Amount"),
                    "agency": a.get("Awarding Agency"),
                }
                for a in awards[:5]
            ],
        }

        briefing = generate_intelligence_summary(
            intel_data,
            topic=f"Daily GovCon intelligence: {', '.join(keywords)}",
        )

        notify_slack(f"*GovCon Daily Intel*\n\n{briefing}")

        return WorkflowResult(
            success=True,
            data={
                "opportunities_found": len(opportunities),
                "awards_found": len(awards),
                "briefing": briefing,
            },
            message=f"Daily intelligence briefing generated ({len(opportunities)} opportunities, {len(awards)} awards)",
        )
