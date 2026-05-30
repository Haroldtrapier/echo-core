"""LinkedIn publishing integration."""
from __future__ import annotations

import json
import urllib.request
from typing import Any

from echo.config import LINKEDIN_ACCESS_TOKEN, LINKEDIN_AUTHOR_URN
from echo.core.logger import get_logger

log = get_logger("echo.integrations.linkedin")

API_URL = "https://api.linkedin.com/v2/ugcPosts"


def post(content: dict[str, Any]) -> str:
    """Post content to LinkedIn. Returns the created post URL.

    content keys:
        body (str): The text of the post
        title (str, optional): Article/share title
        url (str, optional): URL to share
    """
    if not LINKEDIN_ACCESS_TOKEN:
        raise RuntimeError("LINKEDIN_ACCESS_TOKEN not configured")
    if not LINKEDIN_AUTHOR_URN:
        raise RuntimeError("LINKEDIN_AUTHOR_URN not configured (e.g. urn:li:person:ABC123)")

    body = content.get("body", content.get("caption", ""))
    share_url = content.get("url")
    title = content.get("title", "")

    if share_url:
        share_content: dict[str, Any] = {
            "shareCommentary": {"text": body},
            "shareMediaCategory": "ARTICLE",
            "media": [
                {
                    "status": "READY",
                    "description": {"text": body[:256]},
                    "originalUrl": share_url,
                    "title": {"text": title or share_url},
                }
            ],
        }
    else:
        share_content = {
            "shareCommentary": {"text": body},
            "shareMediaCategory": "NONE",
        }

    payload = {
        "author": LINKEDIN_AUTHOR_URN,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": share_content,
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC",
        },
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=data,
        headers={
            "Authorization": f"Bearer {LINKEDIN_ACCESS_TOKEN}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read().decode("utf-8"))

    post_id = result.get("id", "")
    url = f"https://www.linkedin.com/feed/update/{post_id}/" if post_id else ""
    log.info("LinkedIn post created id=%s", post_id)
    return url
