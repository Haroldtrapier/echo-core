"""Publisher module — dry-run and (future) live publish to platforms."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from echo.config import ECHO_ALLOW_LIVE_PUBLISH
from echo.core.logger import get_logger

log = get_logger("echo.modules.publisher")

SUPPORTED_PLATFORMS = ("linkedin", "buffer", "email", "slack", "govcon_cms")


@dataclass
class PublishResult:
    platform: str
    dry_run: bool
    success: bool
    simulated_output: dict[str, Any] | None = None
    live_url: str | None = None
    error: str | None = None


def publish(
    platform: str,
    content: dict[str, Any],
    *,
    dry_run: bool = True,
) -> PublishResult:
    """Publish (or simulate publishing) content to a platform.

    In this release dry_run is always forced True unless ECHO_ALLOW_LIVE_PUBLISH
    is explicitly enabled.
    """
    if not ECHO_ALLOW_LIVE_PUBLISH:
        dry_run = True

    if platform not in SUPPORTED_PLATFORMS:
        return PublishResult(
            platform=platform,
            dry_run=dry_run,
            success=False,
            error=f"Unsupported platform: {platform}. Supported: {SUPPORTED_PLATFORMS}",
        )

    if dry_run:
        log.info("DRY-RUN publish platform=%s", platform)
        return PublishResult(
            platform=platform,
            dry_run=True,
            success=True,
            simulated_output={
                "would_post": True,
                "platform": platform,
                "content_preview": str(content.get("caption", content.get("body", "")))[:200],
                "live_publish_blocked": not ECHO_ALLOW_LIVE_PUBLISH,
            },
        )

    # Live publish — platform-specific dispatch
    return _live_publish(platform, content)


def _live_publish(platform: str, content: dict[str, Any]) -> PublishResult:
    """Dispatch to platform-specific publisher. Extend per platform."""
    try:
        if platform == "linkedin":
            from echo.integrations.linkedin import post as li_post
            url = li_post(content)
            return PublishResult(platform=platform, dry_run=False, success=True, live_url=url)

        if platform == "buffer":
            from echo.integrations.buffer import post as buf_post
            url = buf_post(content)
            return PublishResult(platform=platform, dry_run=False, success=True, live_url=url)

        return PublishResult(
            platform=platform, dry_run=False, success=False,
            error="Live publish not implemented for this platform yet"
        )
    except Exception as exc:
        log.exception("Live publish failed platform=%s: %s", platform, exc)
        return PublishResult(platform=platform, dry_run=False, success=False, error=str(exc))
