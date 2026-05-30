"""GovCon CMS integration — publish content to the internal GovCon content management system."""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

from echo.core.logger import get_logger

log = get_logger("echo.integrations.govcon_cms")

CMS_BASE_URL = os.getenv("GOVCON_CMS_URL", "")
CMS_API_KEY = os.getenv("GOVCON_CMS_API_KEY", "")


def post(content: dict[str, Any]) -> str:
    """Publish a content item to the GovCon CMS. Returns the URL of the created item.

    content keys:
        title (str): Content title
        body (str): HTML or markdown body
        status (str): "draft" | "published" (default: "published")
        tags (list[str], optional): Content tags
        author (str, optional): Author name
        slug (str, optional): URL slug (auto-generated if not provided)
    """
    if not CMS_BASE_URL:
        raise RuntimeError("GOVCON_CMS_URL not configured")
    if not CMS_API_KEY:
        raise RuntimeError("GOVCON_CMS_API_KEY not configured")

    payload = {
        "title": content.get("title", "Untitled"),
        "body": content.get("body", content.get("caption", "")),
        "status": content.get("status", "published"),
        "tags": content.get("tags", []),
        "author": content.get("author", "Echo Automation"),
    }
    if content.get("slug"):
        payload["slug"] = content["slug"]

    data = json.dumps(payload).encode("utf-8")
    url = f"{CMS_BASE_URL.rstrip('/')}/api/content"
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {CMS_API_KEY}",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read().decode("utf-8"))

    item_url = result.get("url", result.get("permalink", ""))
    log.info("GovCon CMS post created url=%s", item_url)
    return item_url


def update_item(item_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    """Update an existing CMS content item by ID."""
    if not CMS_BASE_URL or not CMS_API_KEY:
        raise RuntimeError("GOVCON_CMS_URL and GOVCON_CMS_API_KEY must be configured")

    data = json.dumps(updates).encode("utf-8")
    url = f"{CMS_BASE_URL.rstrip('/')}/api/content/{item_id}"
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {CMS_API_KEY}",
            "X-HTTP-Method-Override": "PATCH",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))
