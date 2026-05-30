"""Weekly GovCon performance report workflow."""
from __future__ import annotations

from typing import Any

from echo.core.registry import register
from echo.core.workflow import BaseWorkflow, WorkflowResult
from echo.modules.analytics import get_summary
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

        # Generate AI narrative
        narrative = generate_intelligence_summary(
            summary,
            topic="Weekly GovCon automation performance",
        )

        # Send Slack notification
        slack_msg = build_summary_notification(summary)
        notify_slack(slack_msg + f"\n\n*AI Narrative:*\n{narrative}")

        return WorkflowResult(
            success=True,
            data={
                "summary": summary,
                "narrative": narrative,
            },
            message="Weekly report generated and dispatched",
        )
