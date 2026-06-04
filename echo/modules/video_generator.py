"""Video generation ("Echo Complete" / TikTok pipeline).

Orchestrates short-form video production from a script. Echo does not render
video itself — it delegates to an external render service via `VIDEO_API_URL`
(a seam you point at e.g. a custom render worker or a service that does
TTS voiceover + render). The service is expected to accept
``{"script","voice"}`` and return JSON containing a ``video_url``.

Always returns a structured dict (never raises); when unconfigured it reports
``status="needs_production"`` so the draft stays gated until a real asset
exists. Honest by design: no provider, no fabricated video.
"""
from __future__ import annotations

import json
import urllib.request
from typing import Any

from echo.config import VIDEO_API_KEY, VIDEO_API_URL, VIDEO_VOICE
from echo.core.logger import get_logger

log = get_logger("echo.modules.video_generator")


def is_configured() -> bool:
    return bool(VIDEO_API_KEY and VIDEO_API_URL)


def generate_video(script: str, *, voice: str | None = None) -> dict[str, Any]:
    """Produce a video from a script.

    Returns ``{"status": ..., "video_url": str|None, "detail": str}`` where
    status ∈ ``produced`` | ``needs_production`` | ``failed``.
    """
    if not is_configured():
        return {
            "status": "needs_production",
            "video_url": None,
            "detail": "VIDEO_API_KEY/VIDEO_API_URL not set — attach a produced video asset.",
        }

    body = {"script": script, "voice": voice or VIDEO_VOICE}
    req = urllib.request.Request(
        VIDEO_API_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {VIDEO_API_KEY}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        url = data.get("video_url") or data.get("url")
        if not url:
            # Async render services may return a job id instead of a URL.
            job = data.get("job_id") or data.get("id")
            return {
                "status": "needs_production",
                "video_url": None,
                "detail": f"render queued (job={job})" if job else "no video_url returned",
            }
        log.info("Video produced via render service")
        return {"status": "produced", "video_url": url, "detail": "ok"}
    except Exception as exc:  # noqa: BLE001
        log.exception("Video generation failed: %s", exc)
        return {"status": "failed", "video_url": None, "detail": str(exc)}
