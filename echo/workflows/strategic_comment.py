"""Strategic comment workflow — draft a value-adding comment for approval.

Replaces the rube "Government Contracting Strategic Comment Generator" recipe.
Approval-first: generates the comment and queues it as a draft
(status ``pending_review``); it is never posted automatically.
"""
from __future__ import annotations

from typing import Any

from echo.core.registry import register
from echo.core.workflow import BaseWorkflow, WorkflowResult
from echo.modules.ai_generator import generate_strategic_comment
from echo.modules.content_store import create_content_item


@register
class StrategicCommentWorkflow(BaseWorkflow):
    slug = "strategic_comment"
    name = "Strategic Comment Generator"
    description = (
        "Drafts a strategic, value-adding comment for a GovCon LinkedIn post and "
        "queues it for human approval before posting."
    )

    def validate(self, payload: dict[str, Any]) -> list[str]:
        errors = []
        if not payload.get("post_context"):
            errors.append("payload.post_context is required (the post text or summary)")
        return errors

    def run(self, db: Any, payload: dict[str, Any]) -> WorkflowResult:
        post_context = payload["post_context"]
        angle = payload.get("angle", "")
        brand = payload.get("brand") or None
        source_url = payload.get("post_url")

        comment_text = generate_strategic_comment(
            post_context, angle=angle, brand=brand or "",
        )

        item = create_content_item(
            db,
            workflow=self.slug,
            platform="linkedin",
            content_type="strategic_comment",
            title=f"Comment: {post_context[:80]}",
            caption=comment_text,
            topic=angle or "engagement",
            brand=brand,
            cta_url=source_url,
            status="pending_review",
        )

        return WorkflowResult(
            success=True,
            data={
                "post_id": item.post_id,
                "comment_text": comment_text,
                "source_url": source_url,
                "status": item.status,
            },
            message=f"Draft strategic comment created (post_id={item.post_id}) — pending approval",
        )
