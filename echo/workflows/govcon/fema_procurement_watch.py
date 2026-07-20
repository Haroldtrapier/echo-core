"""C. FEMA / Disaster Procurement Watch.

Watches FEMA disaster declarations (via the existing FEMA adapter, with a safe
fallback when unavailable) and produces a procurement alert, a contractor action
brief, a readiness/supply opportunity angle, and a Sturgeon handoff CTA — queued
as a reviewable alert draft. Optionally opens a Sturgeon handoff when asked.

The provider interface is mockable: ``pack.safe_disaster_declarations`` fans out
across FEMA + NRS + SEMA and returns ``[]`` on any error, so this runs offline.
FEMA is always live; the NRS (``echo.integrations.nrs``) and SEMA
(``echo.integrations.sema``) adapters follow the same
``get_disaster_declarations(...)`` shape and activate when their ``*_API_URL``
env vars are provisioned — otherwise they safely contribute nothing.
"""
from __future__ import annotations

from typing import Any

from echo.core.registry import register
from echo.core.workflow import WorkflowResult
from echo.modules import sturgeon
from echo.workflows.govcon import pack


@register
class FemaProcurementWatchWorkflow(pack.GovConWorkflow):
    slug = "fema_procurement_watch"
    name = "FEMA / Disaster Procurement Watch"
    description = (
        "Monitors FEMA disaster declarations and drafts a procurement alert with a "
        "contractor action brief, readiness/supply angle, and Sturgeon handoff CTA."
    )
    trigger_type = "scheduled"
    schedule_interval_seconds = 3_600  # hourly disaster watch
    output_type = "alert"
    connector_targets = ("fema", "slack")
    input_schema = {
        "state": "str? — 2-letter state filter",
        "days_back": "int? — lookback window (default 14)",
        "create_handoff": "bool? — also open a Sturgeon handoff for the top signal",
    }

    def run(self, db: Any, payload: dict[str, Any]) -> WorkflowResult:
        state = payload.get("state")
        days_back = int(payload.get("days_back", 14))
        declarations = pack.safe_disaster_declarations(
            state=state, limit=payload.get("limit", 10), days_back=days_back
        )

        body = self._compose(declarations, state)

        queued = pack.queue_draft(
            db,
            workflow=self.slug,
            draft_type="alert",
            title=f"FEMA Procurement Watch — {len(declarations)} signal(s)"
            + (f" ({state})" if state else ""),
            body=body,
            payload=payload,
            topic="FEMA disaster procurement",
            content_type="fema_alert",
            campaign="fema_procurement_watch",
        )

        handoff_id = None
        if payload.get("create_handoff") and declarations:
            ctx = pack.run_ctx(payload)
            top = declarations[0]
            h = sturgeon.create_handoff(
                db,
                opportunity_title=f"Disaster procurement: {top.get('declarationTitle') or top.get('incidentType') or 'FEMA event'}",
                agency="FEMA / DHS",
                summary=body[:1000],
                recommended_next_action="Assess supply/logistics capability and public-assistance eligibility.",
                tenant_id=ctx["tenant_id"],
                workflow_run_id=ctx["run_id"],
                approval_id=queued["approval_id"],
                created_by=self.slug,
                extra={"workflow_id": self.slug, "state": state},
            )
            handoff_id = h.id

        return WorkflowResult(
            success=True,
            data={**queued, "declarations_found": len(declarations), "handoff_id": handoff_id},
            message=(
                f"FEMA procurement watch drafted (approval_id={queued['approval_id']}, "
                f"{len(declarations)} signal(s))"
            ),
        )

    def _compose(self, declarations: list[dict[str, Any]], state: str | None) -> str:
        lines = ["# FEMA / Disaster Procurement Watch", ""]
        lines.append("## Procurement Alert")
        if declarations:
            for d in declarations[:10]:
                itype = d.get("incidentType") or "Incident"
                st = d.get("state") or "—"
                dtitle = d.get("declarationTitle") or ""
                declared = d.get("declarationDate") or ""
                lines.append(f"- {itype} — {st} {('· ' + dtitle) if dtitle else ''} {declared}".rstrip())
        else:
            lines.append("- No active declarations in window. Maintain readiness posture and saved alerts.")
        lines.append("")
        lines.append("## Contractor Action Brief")
        lines.append("- Confirm SAM.gov registration + disaster-relevant NAICS are active.")
        lines.append("- Check state emergency-management and FEMA PA procurement portals for surge RFQs.")
        lines.append("- Line up teaming partners for logistics, debris, temporary power, and supplies.")
        lines.append("")
        lines.append("## Readiness / Supply Opportunity Angle")
        lines.append(
            "- Public-assistance and individual-assistance programs drive rapid supply/logistics "
            "procurement. Position pre-priced catalogs and rapid-response capability now."
        )
        lines.append("")
        lines.append("## Analyze in Sturgeon")
        lines.append(sturgeon.cta_text())
        return "\n".join(lines)
