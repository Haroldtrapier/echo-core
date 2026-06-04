"""Multi-platform social post workflow.

Generates network-appropriate copy for LinkedIn, Facebook, Instagram, or TikTok
and queues it as an approval-first draft. Honest about media requirements:

* Instagram drafts REQUIRE an image (`image_url`) — without one the draft is
  marked ``needs_media`` and the publisher refuses a live post.
* TikTok drafts produce a *script* and REQUIRE a produced video asset
  (`image_url` holds the video URL) — Echo does not generate video.

Publishing (LinkedIn native, or Facebook/Instagram/TikTok via Buffer) is handled
by ``approved_publisher`` after a human approves.
"""
from __future__ import annotations

from typing import Any

from echo.core.registry import register
from echo.core.workflow import BaseWorkflow, WorkflowResult
from echo.modules import image_generator, video_generator
from echo.modules.ai_generator import SOCIAL_PLATFORMS, generate_social_post
from echo.modules.content_store import build_utm_url, create_content_item

DEFAULT_CTA_URL = "https://www.govconcommandcenter.com"

# Networks that must carry a media asset before they can be published.
_MEDIA_REQUIRED = {"instagram": "image", "tiktok": "video"}
# How each network maps to a stored content_type.
_CONTENT_TYPE = {
    "linkedin": "linkedin_post",
    "facebook": "facebook_post",
    "instagram": "instagram_post",
    "tiktok": "tiktok_video",
}


@register
class SocialPostWorkflow(BaseWorkflow):
    slug = "social_post"
    name = "Multi-Platform Social Post"
    description = (
        "Generates platform-appropriate copy for LinkedIn, Facebook, Instagram, or "
        "TikTok and queues an approval-first draft. Instagram needs an image and "
        "TikTok needs a produced video before it can be published."
    )

    def validate(self, payload: dict[str, Any]) -> list[str]:
        errors = []
        platform = payload.get("platform")
        if not platform:
            errors.append("payload.platform is required")
        elif platform not in SOCIAL_PLATFORMS:
            errors.append(f"payload.platform must be one of {', '.join(SOCIAL_PLATFORMS)}")
        if not payload.get("topic"):
            errors.append("payload.topic is required")
        return errors

    def run(self, db: Any, payload: dict[str, Any]) -> WorkflowResult:
        platform = payload["platform"]
        topic = payload["topic"]
        brand = payload.get("brand") or None
        campaign = payload.get("campaign") or "govcon_social"
        image_url = payload.get("image_url")
        cta_base = payload.get("cta_url") or DEFAULT_CTA_URL

        text = generate_social_post(platform, topic, brand=brand or "")

        utm = {"source": platform, "medium": "social",
               "campaign": campaign, "content": _CONTENT_TYPE[platform]}
        cta_url = build_utm_url(cta_base, **utm)

        media_kind = _MEDIA_REQUIRED.get(platform)

        # Optionally auto-produce the required asset up front.
        media_production = None
        if media_kind and not image_url and payload.get("auto_media"):
            if platform == "instagram":
                image_url = image_generator.generate_image(topic, brand=brand or "")
                media_production = {"kind": "image", "produced": bool(image_url),
                                    "provider_configured": image_generator.is_configured()}
            elif platform == "tiktok":
                vres = video_generator.generate_video(text)
                if vres.get("video_url"):
                    image_url = vres["video_url"]
                media_production = {"kind": "video", **vres}

        needs_media = bool(media_kind) and not image_url
        status = "needs_media" if needs_media else "pending_review"

        item = create_content_item(
            db,
            workflow=self.slug,
            platform=platform,
            content_type=_CONTENT_TYPE[platform],
            title=f"{platform.title()}: {topic}"[:200],
            caption=text,
            topic=topic,
            brand=brand,
            cta_text=payload.get("cta_text") or "Learn more",
            cta_url=cta_url,
            utm=utm,
            image_url=image_url,
            status=status,
        )

        msg = f"Draft {platform} post created (post_id={item.post_id})"
        if needs_media:
            msg += f" — needs {media_kind} before it can be published"
        else:
            msg += " — pending approval"

        return WorkflowResult(
            success=True,
            data={
                "post_id": item.post_id,
                "platform": platform,
                "content_type": item.content_type,
                "text": text,
                "status": item.status,
                "needs_media": needs_media,
                "media_kind": media_kind,
                "media_production": media_production,
                "image_url": image_url,
                "cta_url": cta_url,
            },
            message=msg,
        )
