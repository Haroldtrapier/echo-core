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

        scheduled_at = payload.get("scheduled_at")  # ISO8601; Buffer schedules it

        # Resolve content: inline dict, or load the draft ContentItem by post_id.
        content = payload.get("content")
        content_item = get_content_by_post_id(db, post_id) if post_id else None
        if content is None and content_item is not None:
            content = {"body": content_item.caption, "caption": content_item.caption}
            # Include the UTM-tagged CTA link so it travels with the post.
            if content_item.cta_url:
                content["url"] = content_item.cta_url
        if content is None:
            content = {}
        if scheduled_at and "scheduled_at" not in content:
            content["scheduled_at"] = scheduled_at

        # Attach media + note per-network media requirements (IG image, TikTok video).
        media_required: str | None = None
        if content_item is not None:
            if content_item.image_url:
                content["image_url"] = content_item.image_url
            ct = content_item.content_type or ""
            if ct == "instagram_post":
                media_required = "image"
            elif ct == "tiktok_video":
                media_required = "video"

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

        # Block a LIVE publish of Instagram/TikTok without the required media asset.
        from echo.config import ECHO_ALLOW_LIVE_PUBLISH
        will_publish_live = ECHO_ALLOW_LIVE_PUBLISH and not payload.get("dry_run", True)
        if media_required and not content.get("image_url") and will_publish_live:
            return WorkflowResult(
                success=False,
                data={"post_id": post_id, "approval_id": approval_id,
                      "needs_media": media_required},
                message=(f"Cannot publish: {content_item.content_type} requires a "
                         f"{media_required} asset — set image_url on the draft first."),
            )

        # Publish (dry-run unless ECHO_ALLOW_LIVE_PUBLISH=true)
        result = publish(platform, content, dry_run=payload.get("dry_run", True))

        # Determine job status: failed / dry_run / scheduled / published.
        is_scheduled = bool(scheduled_at)
        if not result.success:
            job_status = "failed"
        elif result.dry_run:
            job_status = "dry_run"
        elif is_scheduled:
            job_status = "scheduled"
        else:
            job_status = "published"

        # Record a publishing job for the cockpit queue.
        job = record_publishing_job(
            db,
            post_id=post_id,
            platform=platform,
            status=job_status,
            published_url=result.live_url,
            external_post_id=result.live_url,
            error_message=result.error,
            scheduling_mode="scheduled" if is_scheduled else "immediate",
        )

        # Advance the linked content item's state.
        if content_item is not None and result.success:
            mark_content_published(db, content_item, live=not result.dry_run,
                                   published_url=result.live_url,
                                   scheduled=is_scheduled)

        return WorkflowResult(
            success=result.success,
            data={
                "approval_id": approval_id,
                "platform": platform,
                "post_id": post_id,
                "publishing_job_id": job.id,
                "job_status": job_status,
                "scheduled": is_scheduled,
                "scheduled_at": scheduled_at,
                "dry_run": result.dry_run,
                "live_url": result.live_url,
                "simulated_output": result.simulated_output,
                "error": result.error,
            },
            message=(
                f"Content {job_status} "
                f"to {platform} ({'ok' if result.success else 'failed'})"
            ),
        )
