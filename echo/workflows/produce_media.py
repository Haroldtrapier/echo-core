"""Produce the media asset a draft needs (Instagram image / TikTok video).

Given a draft `post_id`, generates the missing asset and attaches it, flipping
the draft from ``needs_media`` to ``pending_review``. Honest about provider
availability: with no image/video provider configured it reports
``needs_production`` and leaves the draft gated.
"""
from __future__ import annotations

from typing import Any

from echo.core.registry import register
from echo.core.workflow import BaseWorkflow, WorkflowResult
from echo.modules import image_generator, video_generator
from echo.modules.content_store import attach_media, get_content_by_post_id


@register
class ProduceMediaWorkflow(BaseWorkflow):
    slug = "produce_media"
    name = "Produce Media Asset"
    description = (
        "Generates the image (Instagram) or video (TikTok) a draft requires and "
        "attaches it, moving the draft to pending_review. Needs an image/video "
        "provider configured; otherwise reports needs_production."
    )

    def validate(self, payload: dict[str, Any]) -> list[str]:
        errors = []
        if not payload.get("post_id"):
            errors.append("payload.post_id is required")
        return errors

    def run(self, db: Any, payload: dict[str, Any]) -> WorkflowResult:
        post_id = payload["post_id"]
        item = get_content_by_post_id(db, post_id)
        if item is None:
            return WorkflowResult(success=False, data={"post_id": post_id},
                                  message=f"No content item for post_id {post_id}")

        ctype = item.content_type or ""
        if item.image_url:
            return WorkflowResult(
                success=True,
                data={"post_id": post_id, "image_url": item.image_url, "status": item.status},
                message="Draft already has a media asset",
            )

        if ctype == "instagram_post":
            url = image_generator.generate_image(item.topic or item.title or "", brand=item.brand or "")
            if not url:
                return WorkflowResult(
                    success=False,
                    data={"post_id": post_id, "kind": "image", "status": "needs_media",
                          "provider_configured": image_generator.is_configured()},
                    message="Image not produced — set IMAGE_API_KEY or supply image_url.",
                )
            attach_media(db, item, url)
            return WorkflowResult(
                success=True,
                data={"post_id": post_id, "kind": "image", "image_url": url, "status": item.status},
                message=f"Image attached to {post_id} — now {item.status}",
            )

        if ctype == "tiktok_video":
            result = video_generator.generate_video(item.caption or "")
            if result["status"] != "produced" or not result.get("video_url"):
                return WorkflowResult(
                    success=False,
                    data={"post_id": post_id, "kind": "video", "status": "needs_media",
                          "production": result,
                          "provider_configured": video_generator.is_configured()},
                    message=f"Video not produced ({result['status']}): {result['detail']}",
                )
            attach_media(db, item, result["video_url"])
            return WorkflowResult(
                success=True,
                data={"post_id": post_id, "kind": "video",
                      "video_url": result["video_url"], "status": item.status},
                message=f"Video attached to {post_id} — now {item.status}",
            )

        return WorkflowResult(
            success=False,
            data={"post_id": post_id, "content_type": ctype},
            message=f"content_type {ctype!r} does not require produced media",
        )
