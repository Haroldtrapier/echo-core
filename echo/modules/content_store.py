"""Content store — persist cockpit read-models (ContentItem, PublishingJob).

This is the bridge that makes generated content show up in the Imani cockpit's
Content Queue and Publishing Jobs views. Workflows call these helpers so the
persistence shape lives in one place and stays consistent across workflows.

The lifecycle mirrors the approval-first model:

    draft / pending_review  →  (human approves)  →  approved
                                                      │
                                            (publish, live only)
                                                      ▼
                                                  published
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

from sqlalchemy.orm import Session

from echo.db import ContentItem, PublishingJob


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_post_id() -> str:
    return "post_" + uuid.uuid4().hex[:12]


def build_utm_url(
    base_url: str,
    *,
    source: str | None = None,
    medium: str | None = None,
    campaign: str | None = None,
    content: str | None = None,
) -> str:
    """Append UTM parameters to a CTA URL (skips empties)."""
    params = {
        k: v
        for k, v in {
            "utm_source": source,
            "utm_medium": medium,
            "utm_campaign": campaign,
            "utm_content": content,
        }.items()
        if v
    }
    if not params:
        return base_url
    sep = "&" if "?" in base_url else "?"
    return f"{base_url}{sep}{urlencode(params)}"


def create_content_item(
    db: Session,
    *,
    workflow: str,
    platform: str,
    caption: str,
    title: str | None = None,
    topic: str | None = None,
    brand: str | None = None,
    content_type: str | None = None,
    cta_text: str | None = None,
    cta_url: str | None = None,
    utm: dict[str, str] | None = None,
    status: str = "draft",
) -> ContentItem:
    """Persist a new content item (defaults to an unapproved, unpublished draft)."""
    utm = utm or {}
    item = ContentItem(
        post_id=new_post_id(),
        brand=brand,
        workflow=workflow,
        content_type=content_type or platform,
        topic=topic,
        title=title,
        caption=caption,
        cta_text=cta_text,
        cta_url=cta_url,
        utm_source=utm.get("source"),
        utm_medium=utm.get("medium"),
        utm_campaign=utm.get("campaign"),
        utm_content=utm.get("content"),
        status=status,
        approved=False,
        published=False,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def get_content_by_post_id(db: Session, post_id: str) -> ContentItem | None:
    return db.query(ContentItem).filter(ContentItem.post_id == post_id).first()


def record_publishing_job(
    db: Session,
    *,
    post_id: str | None,
    platform: str,
    status: str,
    published_url: str | None = None,
    external_post_id: str | None = None,
    error_message: str | None = None,
) -> PublishingJob:
    """Record a publishing attempt. ``status`` is one of
    ``published`` | ``dry_run`` | ``failed`` | ``pending``."""
    job = PublishingJob(
        post_id=post_id,
        platform=platform,
        status=status,
        attempt_count=1,
        external_post_id=external_post_id,
        published_url=published_url,
        published_at=_utcnow() if status == "published" else None,
        error_message=error_message,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def mark_content_published(
    db: Session,
    item: ContentItem,
    *,
    live: bool,
    published_url: str | None = None,
) -> ContentItem:
    """Advance an approved item's publishing state.

    Live publish → ``published=True`` with URL + timestamp (status ``published``).
    Dry-run → stays ``published=False`` (status ``approved``) — nothing left the
    building, so we never claim it did.
    """
    item.approved = True
    if live:
        item.published = True
        item.published_url = published_url
        item.published_at = _utcnow()
        item.status = "published"
    else:
        item.status = "approved"
    item.updated_at = _utcnow()
    db.commit()
    db.refresh(item)
    return item
