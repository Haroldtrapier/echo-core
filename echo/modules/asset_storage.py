"""Asset storage — host generated media at a public URL (Supabase Storage).

When an image provider returns raw bytes (base64) instead of a hosted URL, the
bytes must live somewhere Buffer/Instagram can fetch. This uploads to a Supabase
Storage bucket and returns the public URL.

Graceful by design: if storage is not configured it returns ``None`` and callers
treat the asset as unavailable (the draft stays ``needs_media``) — Echo never
returns an unusable data blob as if it were a real URL.
"""
from __future__ import annotations

import urllib.request
import uuid
from typing import Optional

from echo.config import MEDIA_BUCKET, SUPABASE_SERVICE_KEY, SUPABASE_URL
from echo.core.logger import get_logger

log = get_logger("echo.modules.asset_storage")


def is_configured() -> bool:
    return bool(SUPABASE_URL and SUPABASE_SERVICE_KEY)


def public_url(path: str) -> str:
    base = SUPABASE_URL.rstrip("/")
    return f"{base}/storage/v1/object/public/{MEDIA_BUCKET}/{path}"


def upload_bytes(
    data: bytes,
    *,
    content_type: str = "image/png",
    ext: str = "png",
    prefix: str = "echo",
) -> Optional[str]:
    """Upload bytes to the media bucket and return the public URL (or ``None``)."""
    if not is_configured():
        log.warning("SUPABASE_URL/SUPABASE_SERVICE_KEY not set — cannot host asset")
        return None

    path = f"{prefix}/{uuid.uuid4().hex}.{ext}"
    url = f"{SUPABASE_URL.rstrip('/')}/storage/v1/object/{MEDIA_BUCKET}/{path}"
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
            "Content-Type": content_type,
            "x-upsert": "true",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            if resp.status not in (200, 201):
                log.warning("asset upload returned status %s", resp.status)
                return None
        hosted = public_url(path)
        log.info("Hosted asset at %s", hosted)
        return hosted
    except Exception as exc:  # noqa: BLE001
        log.exception("Asset upload failed: %s", exc)
        return None
