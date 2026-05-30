"""SAM.gov opportunity watch workflow — monitor and alert on new contract opportunities."""
from __future__ import annotations

from typing import Any

from echo.core.registry import register
from echo.core.workflow import BaseWorkflow, WorkflowResult
from echo.integrations.sam_gov import search_opportunities
from echo.modules.ai_generator import generate_intelligence_summary
from echo.modules.notifications import notify_slack


@register
class SamOpportunityWatchWorkflow(BaseWorkflow):
    slug = "sam_opportunity_watch"
    name = "SAM.gov Opportunity Watch"
    description = (
        "Searches SAM.gov for new contract opportunities matching configured keywords, "
        "generates an AI briefing on top matches, and sends a Slack alert."
    )

    def validate(self, payload: dict[str, Any]) -> list[str]:
        errors = []
        if not payload.get("keywords"):
            errors.append("payload.keywords is required (string or list of strings)")
        return errors

    def run(self, db: Any, payload: dict[str, Any]) -> WorkflowResult:
        raw_keywords = payload["keywords"]
        if isinstance(raw_keywords, list):
            keywords_str = " ".join(raw_keywords)
        else:
            keywords_str = raw_keywords

        limit = payload.get("limit", 10)
        days_back = payload.get("days_back", 7)
        naics_code = payload.get("naics_code")
        set_aside = payload.get("set_aside")

        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        posted_from = (now - timedelta(days=days_back)).strftime("%m/%d/%Y")

        opportunities = search_opportunities(
            keywords_str,
            limit=limit,
            posted_from=posted_from,
            naics_code=naics_code,
            set_aside=set_aside,
        )

        if not opportunities:
            return WorkflowResult(
                success=True,
                data={"opportunities_found": 0},
                message=f"No SAM.gov opportunities found for: {keywords_str}",
            )

        formatted = [
            {
                "title": o.get("title"),
                "notice_id": o.get("noticeId"),
                "solicitation": o.get("solicitationNumber"),
                "agency": o.get("fullParentPathName"),
                "naics": o.get("naicsCode"),
                "posted": o.get("postedDate"),
                "deadline": o.get("responseDeadLine"),
                "type": o.get("baseType"),
                "set_aside": o.get("typeOfSetAsideDescription"),
                "link": o.get("uiLink"),
            }
            for o in opportunities
        ]

        briefing = generate_intelligence_summary(
            {"keywords": keywords_str, "opportunities": formatted},
            topic=f"SAM.gov opportunities: {keywords_str}",
        )

        alert = (
            f"*SAM.gov Opportunity Watch* — {len(opportunities)} new opportunity(ies) "
            f"for `{keywords_str}`\n\n{briefing}"
        )
        notify_slack(alert)

        return WorkflowResult(
            success=True,
            data={
                "opportunities_found": len(opportunities),
                "opportunities": formatted,
                "briefing": briefing,
            },
            message=f"Found {len(opportunities)} SAM.gov opportunity(ies) for: {keywords_str}",
        )
