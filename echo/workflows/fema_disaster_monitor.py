"""FEMA disaster monitor workflow — watch for new disaster declarations."""
from __future__ import annotations

from typing import Any

from echo.core.registry import register
from echo.core.workflow import BaseWorkflow, WorkflowResult
from echo.integrations.fema import get_disaster_declarations
from echo.modules.ai_generator import generate_intelligence_summary
from echo.modules.notifications import notify_slack


@register
class FemaDisasterMonitorWorkflow(BaseWorkflow):
    slug = "fema_disaster_monitor"
    name = "FEMA Disaster Monitor"
    description = (
        "Pulls recent FEMA disaster declarations, generates an AI brief on affected regions "
        "and public assistance opportunities, and sends a Slack alert."
    )

    def run(self, db: Any, payload: dict[str, Any]) -> WorkflowResult:
        state = payload.get("state")
        days_back = payload.get("days_back", 14)
        disaster_type = payload.get("disaster_type")
        limit = payload.get("limit", 10)

        declarations = get_disaster_declarations(
            state=state,
            disaster_type=disaster_type,
            limit=limit,
            days_back=days_back,
        )

        if not declarations:
            return WorkflowResult(
                success=True,
                data={"declarations_found": 0},
                message="No new FEMA declarations in the specified window",
            )

        intel_data = {
            "source": "FEMA OpenFEMA",
            "declarations": [
                {
                    "disaster_number": d.get("disasterNumber"),
                    "type": d.get("incidentType"),
                    "title": d.get("declarationTitle"),
                    "state": d.get("state"),
                    "declared": d.get("declarationDate"),
                    "incident_begin": d.get("incidentBeginDate"),
                    "incident_end": d.get("incidentEndDate"),
                }
                for d in declarations
            ],
        }

        briefing = generate_intelligence_summary(
            intel_data,
            topic="FEMA disaster declarations — GovCon opportunities",
        )

        notify_slack(
            f"*FEMA Disaster Monitor* — {len(declarations)} new declaration(s)\n\n{briefing}",
            level="warning",
        )

        return WorkflowResult(
            success=True,
            data={
                "declarations_found": len(declarations),
                "briefing": briefing,
                "declarations": intel_data["declarations"],
            },
            message=f"FEMA monitor found {len(declarations)} declaration(s)",
        )
