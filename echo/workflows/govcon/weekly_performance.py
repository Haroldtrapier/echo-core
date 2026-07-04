"""F. Weekly Performance Tracker.

Summarizes the past week from the analytics event stream: workflows run, drafts
created, approvals, rejections, published/marked-ready items, Sturgeon handoffs,
plus recommendations for next week. Saved as a reviewable report draft.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import func

from echo.core.registry import register
from echo.core.workflow import WorkflowResult
from echo.db import EchoSturgeonHandoff
from echo.modules import events
from echo.workflows.govcon import pack


@register
class WeeklyPerformanceTrackerWorkflow(pack.GovConWorkflow):
    slug = "weekly_performance_tracker"
    name = "Weekly Performance Tracker"
    description = (
        "Summarizes the week's Echo GovCon activity (runs, drafts, approvals, "
        "rejections, published items, Sturgeon handoffs) with recommendations."
    )
    trigger_type = "scheduled"
    output_type = "report"
    approval_required = False
    connector_targets = ("slack",)
    input_schema = {"days_back": "int? — window in days (default 7)"}

    def run(self, db: Any, payload: dict[str, Any]) -> WorkflowResult:
        days_back = int(payload.get("days_back", 7))
        ctx = pack.run_ctx(payload)
        since = events.window_since(days_back)
        counts = events.event_counts(db, since=since)

        handoffs = (
            db.query(func.count(EchoSturgeonHandoff.id))
            .filter(EchoSturgeonHandoff.created_at >= since)
            .scalar()
            or 0
        )

        metrics = {
            "workflows_run": counts.get(events.EVENT_WORKFLOW_STARTED, 0),
            "workflows_completed": counts.get(events.EVENT_WORKFLOW_COMPLETED, 0),
            "workflows_failed": counts.get(events.EVENT_WORKFLOW_FAILED, 0),
            "drafts_created": counts.get(events.EVENT_DRAFT_CREATED, 0),
            "drafts_approved": counts.get(events.EVENT_DRAFT_APPROVED, 0),
            "drafts_rejected": counts.get(events.EVENT_DRAFT_REJECTED, 0),
            "published_or_ready": counts.get(events.EVENT_DRAFT_PUBLISHED_OR_READY, 0),
            "sturgeon_handoffs": int(handoffs),
            "lead_nurture_batches": counts.get(events.EVENT_LEAD_NURTURE_CREATED, 0),
        }

        body = self._compose(days_back, metrics)

        queued = pack.queue_draft(
            db,
            workflow=self.slug,
            draft_type="brief",
            title=f"Weekly Performance — last {days_back}d",
            body=body,
            payload=payload,
            topic="weekly_performance",
            content_type="weekly_report",
            campaign="weekly_performance_tracker",
        )

        return WorkflowResult(
            success=True,
            data={**queued, "metrics": metrics, "days_back": days_back, "brief": body},
            message=f"Weekly performance report drafted (approval_id={queued['approval_id']})",
        )

    def _compose(self, days_back: int, m: dict[str, int]) -> str:
        approved = m["drafts_approved"]
        rejected = m["drafts_rejected"]
        reviewed = approved + rejected
        approval_rate = round(approved / reviewed * 100, 1) if reviewed else 0.0

        lines = [
            f"# Weekly Performance Tracker — last {days_back} days",
            "",
            "## Activity",
            f"- Workflows run: {m['workflows_run']} "
            f"(completed {m['workflows_completed']}, failed {m['workflows_failed']})",
            f"- Drafts created: {m['drafts_created']}",
            f"- Approvals: {approved}  ·  Rejections: {rejected}  "
            f"(approval rate {approval_rate}%)",
            f"- Published / marked ready: {m['published_or_ready']}",
            f"- Sturgeon handoffs: {m['sturgeon_handoffs']}",
            f"- Lead-nurture batches: {m['lead_nurture_batches']}",
            "",
            "## CTA Clicks",
            "- CTA click tracking is attributed via GA4 in the analytics summary "
            "(configure GA4 to populate). No click data included in this snapshot.",
            "",
            "## Recommendations for Next Week",
        ]
        if m["drafts_created"] == 0:
            lines.append("- Pipeline is empty — schedule the Daily GovCon Brief to seed drafts.")
        if reviewed and approval_rate < 50:
            lines.append("- Approval rate is low — tighten prompts/targeting so drafts need less rework.")
        if m["sturgeon_handoffs"] == 0 and approved > 0:
            lines.append("- Approved content isn't converting to Sturgeon handoffs — add clearer CTAs.")
        if m["workflows_failed"] > 0:
            lines.append("- Investigate failed runs in /logs and /runs?status=failed.")
        if len(lines) == 0 or lines[-1].endswith("Next Week"):
            lines.append("- Healthy week — maintain cadence and expand keyword/agency coverage.")
        return "\n".join(lines)
