"""Approved publisher workflow — publish content that has been human-approved."""
from __future__ import annotations

from typing import Any

from echo.core.registry import register
from echo.core.workflow import BaseWorkflow, WorkflowResult
from echo.modules.approval import create_approval, decide, get_pending
from echo.modules.publisher import publish


@register
class ApprovedPublisherWorkflow(BaseWorkflow):
    slug = "approved_publisher"
    name = "Approved Publisher"
    description = (
        "Routes content through a human approval gate before publishing. "
        "Creates a pending approval record on first run; on second run (after approval), "
        "publishes to the specified platform."
    )

    def validate(self, payload: dict[str, Any]) -> list[str]:
        errors = []
        if not payload.get("platform"):
            errors.append("payload.platform is required")
        if not payload.get("content"):
            errors.append("payload.content (dict) is required")
        return errors

    def run(self, db: Any, payload: dict[str, Any]) -> WorkflowResult:
        platform = payload["platform"]
        content = payload["content"]
        run_id = payload.get("run_id")
        approval_id = payload.get("approval_id")

        # If an approval_id is provided, check its status and publish if approved
        if approval_id:
            from echo.db import Approval
            approval = db.query(Approval).filter(Approval.id == approval_id).first()
            if approval is None:
                return WorkflowResult(
                    success=False,
                    data={"approval_id": approval_id},
                    message=f"Approval {approval_id} not found",
                )
            if approval.status == "pending":
                return WorkflowResult(
                    success=True,
                    data={"approval_id": approval_id, "status": "pending"},
                    message="Approval is still pending — waiting for decision",
                )
            if approval.status == "rejected":
                return WorkflowResult(
                    success=False,
                    data={"approval_id": approval_id, "status": "rejected",
                          "note": approval.decision_note},
                    message=f"Content rejected by {approval.decision_by}",
                )
            # approved — fall through to publish

        # Request approval if none provided
        if not approval_id:
            approval = create_approval(
                db,
                run_id=run_id,
                requested_by=payload.get("requested_by", "echo_workflow"),
                reason=f"Publish to {platform}: {str(content)[:200]}",
                resume_payload=payload,
            )
            return WorkflowResult(
                success=True,
                data={"approval_id": approval.id, "status": "pending"},
                message=f"Approval requested — ID: {approval.id}. Re-run with approval_id once approved.",
            )

        # Publish
        result = publish(platform, content, dry_run=payload.get("dry_run", True))
        return WorkflowResult(
            success=result.success,
            data={
                "approval_id": approval_id,
                "platform": platform,
                "dry_run": result.dry_run,
                "live_url": result.live_url,
                "simulated_output": result.simulated_output,
                "error": result.error,
            },
            message=(
                f"Content {'published' if not result.dry_run else 'dry-run published'} "
                f"to {platform} ({'ok' if result.success else 'failed'})"
            ),
        )
