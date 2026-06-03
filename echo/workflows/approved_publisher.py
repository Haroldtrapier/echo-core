"""Approved publisher workflow — publish content that has been human-approved."""
from __future__ import annotations

from typing import Any

from echo.core.registry import register
from echo.core.workflow import BaseWorkflow, WorkflowResult
from echo.modules.approval import create_approval, decide, get_pending
from echo.modules.content_store import (
    get_content_by_post_id,
    mark_content_published,
    record_publishing_job,
)
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
        # Either an inline content dict OR a post_id referencing a draft ContentItem.
        if not payload.get("content") and not payload.get("post_id"):
            errors.append("payload.content (dict) or payload.post_id is required")
        return errors

    def run(self, db: Any, payload: dict[str, Any]) -> WorkflowResult:
        platform = payload["platform"]
        run_id = payload.get("run_id")
        approval_id = payload.get("approval_id")
        post_id = payload.get("post_id")

        # Resolve content: inline dict, or load the draft ContentItem by post_id.
        content = payload.get("content")
        content_item = get_content_by_post_id(db, post_id) if post_id else None
        if content is None and content_item is not None:
            content = {"body": content_item.caption, "caption": content_item.caption}
        if content is None:
            content = {}

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

        # Publish (dry-run unless ECHO_ALLOW_LIVE_PUBLISH=true)
        result = publish(platform, content, dry_run=payload.get("dry_run", True))

        # Record a publishing job for the cockpit queue.
        job = record_publishing_job(
            db,
            post_id=post_id,
            platform=platform,
            status=("published" if (result.success and not result.dry_run)
                    else "dry_run" if result.success else "failed"),
            published_url=result.live_url,
            error_message=result.error,
        )

        # Advance the linked content item's state (approved → published if live).
        if content_item is not None and result.success:
            mark_content_published(db, content_item, live=not result.dry_run,
                                   published_url=result.live_url)

        return WorkflowResult(
            success=result.success,
            data={
                "approval_id": approval_id,
                "platform": platform,
                "post_id": post_id,
                "publishing_job_id": job.id,
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
