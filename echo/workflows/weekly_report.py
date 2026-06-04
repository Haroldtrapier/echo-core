"""Weekly GovCon performance report workflow."""
from __future__ import annotations

from typing import Any

from echo.core.registry import register
from echo.core.workflow import BaseWorkflow, WorkflowResult
from echo.modules.analytics import get_campaign_attribution, get_summary
from echo.modules.ai_generator import generate_intelligence_summary
from echo.modules.notifications import build_summary_notification, notify_slack


@register
class WeeklyReportWorkflow(BaseWorkflow):
    slug = "weekly_report"
    name = "Weekly GovCon Report"
    description = (
        "Aggregates weekly platform metrics, generates an AI narrative summary, "
        "and sends a Slack digest."
    )

    def run(self, db: Any, payload: dict[str, Any]) -> WorkflowResult:
        # Pull live analytics from the database
        summary = get_summary(db)

        # Attribute clicks/conversions to campaigns via GA4 (DB-only if unset)
        attribution = get_campaign_attribution(db, days_back=payload.get("days_back", 7))

        # Generate AI narrative over both
        narrative = generate_intelligence_summary(
            {"summary": summary, "attribution": attribution},
            topic="Weekly GovCon automation performance + campaign attribution",
        )

        # Send Slack notification
        slack_msg = build_summary_notification(summary)
        notify_slack(slack_msg + f"\n\n*AI Narrative:*\n{narrative}")

        return WorkflowResult(
            success=True,
            data={
                "summary": summary,
                "attribution": attribution,
                "narrative": narrative,
            },
            message="Weekly report generated and dispatched",
        )
