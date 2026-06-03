"""LinkedIn signal post workflow — generate a GovCon post and queue it for approval.

Approval-first: this generates the post and persists it as a *draft* ContentItem
(status ``pending_review``) with a UTM-tagged CTA, so it appears in the cockpit
Content Queue. Publishing is handled separately by ``approved_publisher`` once a
human approves it — this workflow never publishes on its own.
"""
from __future__ import annotations

from typing import Any

from echo.core.registry import register
from echo.core.workflow import BaseWorkflow, WorkflowResult
from echo.modules.ai_generator import generate_linkedin_post
from echo.modules.content_store import build_utm_url, create_content_item

# Default CTA destination for GovCon signal posts.
DEFAULT_CTA_URL = "https://www.govconcommandcenter.com"


@register
class LinkedInSignalPostWorkflow(BaseWorkflow):
    slug = "linkedin_signal_post"
    name = "LinkedIn Signal Post"
    description = (
        "Generates a GovCon-focused LinkedIn post via Claude and queues it as a "
        "draft (with CTA + UTM) for human approval. Publishing is done by the "
        "approved_publisher workflow."
    )

    def validate(self, payload: dict[str, Any]) -> list[str]:
        errors = []
        if not payload.get("topic"):
            errors.append("payload.topic is required")
        return errors

    def run(self, db: Any, payload: dict[str, Any]) -> WorkflowResult:
        topic = payload["topic"]
        brand = payload.get("brand") or None
        campaign = payload.get("campaign") or "govcon_signal"
        cta_base = payload.get("cta_url") or DEFAULT_CTA_URL
        cta_text = payload.get("cta_text") or "See live GovCon opportunities"

        post_text = generate_linkedin_post(topic, brand=brand or "")

        utm = {"source": "linkedin", "medium": "social",
               "campaign": campaign, "content": "signal_post"}
        cta_url = build_utm_url(cta_base, **utm)

        item = create_content_item(
            db,
            workflow=self.slug,
            platform="linkedin",
            title=f"LinkedIn Signal: {topic}"[:200],
            caption=post_text,
            topic=topic,
            brand=brand,
            content_type="linkedin_post",
            cta_text=cta_text,
            cta_url=cta_url,
            utm=utm,
            status="pending_review",
        )

        return WorkflowResult(
            success=True,
            data={
                "post_id": item.post_id,
                "content_id": item.id,
                "post_text": post_text,
                "status": item.status,
                "approved": item.approved,
                "published": item.published,
                "cta_url": cta_url,
            },
            message=f"Draft LinkedIn post created (post_id={item.post_id}) — pending approval",
        )
