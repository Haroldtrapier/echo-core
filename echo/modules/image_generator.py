"""Image generation for Instagram creative.

Calls an OpenAI-compatible images API when `IMAGE_API_KEY` is set, returning a
hosted image URL. Degrades gracefully to ``None`` when unconfigured or on
failure — callers then keep the draft in ``needs_media`` rather than publishing
without an image.
"""
from __future__ import annotations

import json
import urllib.request
from typing import Optional

from echo.config import IMAGE_API_BASE, IMAGE_API_KEY, IMAGE_MODEL, IMAGE_SIZE
from echo.core.logger import get_logger

log = get_logger("echo.modules.image_generator")


def is_configured() -> bool:
    return bool(IMAGE_API_KEY)


def _prompt_for(topic: str, brand: str = "") -> str:
    base = (
        "Create a clean, professional social graphic for a government-contracting "
        f"(GovCon) Instagram post about: {topic}. Modern, high-contrast, minimal text, "
        "trustworthy and corporate. No logos, no watermarks."
    )
    return base + (f" Brand tone: {brand}." if brand else "")


def generate_image(topic: str, *, brand: str = "", size: Optional[str] = None) -> Optional[str]:
    """Generate an image and return its URL, or ``None`` if unavailable."""
    if not is_configured():
        log.warning("IMAGE_API_KEY not set — skipping image generation")
        return None

    body = {
        "model": IMAGE_MODEL,
        "prompt": _prompt_for(topic, brand),
        "size": size or IMAGE_SIZE,
        "n": 1,
    }
    req = urllib.request.Request(
        f"{IMAGE_API_BASE.rstrip('/')}/images/generations",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {IMAGE_API_KEY}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        item = (data.get("data") or [{}])[0]
        url = item.get("url")
        if not url and item.get("b64_json"):
            # Some models return base64; hosting that is an infra concern — surface
            # honestly rather than returning an unusable data blob.
            log.warning("image API returned base64; no host configured — treating as unavailable")
            return None
        log.info("Generated image for topic=%r", topic)
        return url
    except Exception as exc:  # noqa: BLE001
        log.exception("Image generation failed: %s", exc)
        return None
