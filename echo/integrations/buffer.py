"""Buffer publishing integration."""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

from echo.config import BUFFER_API_KEY
from echo.core.logger import get_logger

log = get_logger("echo.integrations.buffer")

API_BASE = "https://api.bufferapp.com/1"


def _get_profiles() -> list[dict[str, Any]]:
    """Fetch connected Buffer profiles."""
    url = f"{API_BASE}/profiles.json?access_token={BUFFER_API_KEY}"
    with urllib.request.urlopen(url, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def post(content: dict[str, Any], *, profile_ids: list[str] | None = None) -> str:
    """Queue a post to Buffer. Returns a comma-separated string of created update IDs.

    content keys:
        body / caption (str): The post text
        url (str, optional): Link to include
        scheduled_at (str, optional): ISO timestamp for scheduled posting
    """
    if not BUFFER_API_KEY:
        raise RuntimeError("BUFFER_API_KEY not configured")

    body = content.get("body", content.get("caption", ""))
    url_to_share = content.get("url", "")
    scheduled_at = content.get("scheduled_at")

    # Resolve profile IDs — use provided or fetch first connected profile
    if not profile_ids:
        profiles = _get_profiles()
        profile_ids = [p["id"] for p in profiles[:1]]
    if not profile_ids:
        raise RuntimeError("No Buffer profiles found")

    text = body
    if url_to_share:
        text = f"{body}\n{url_to_share}"

    params: dict[str, Any] = {
        "access_token": BUFFER_API_KEY,
        "text": text,
        "profile_ids[]": profile_ids,
    }
    if scheduled_at:
        import calendar
        from datetime import datetime
        dt = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
        params["scheduled_at"] = calendar.timegm(dt.timetuple())

    data = urllib.parse.urlencode(params, doseq=True).encode("utf-8")
    req = urllib.request.Request(
        f"{API_BASE}/updates/create.json",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read().decode("utf-8"))

    updates = result.get("updates", [])
    update_ids = [u["id"] for u in updates]
    log.info("Buffer updates created ids=%s", update_ids)
    return ",".join(update_ids)
