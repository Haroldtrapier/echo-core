"""Approval-first publishing (Phase 2).

The single hard guard for shipping an approved draft through a connector:

    LIVE publish happens ONLY IF
        the approval is approved/ready  AND  ECHO_ALLOW_LIVE_PUBLISH is true.

Anything else is a dry-run that touches no external service. Default is dry-run.
This never bypasses ``publisher``'s own live gate — it adds an approval gate on top.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from echo.config import ECHO_ALLOW_LIVE_PUBLISH
from echo.core.logger import get_logger
from echo.db import Approval, ContentItem
from echo.modules import connectors, events

log = get_logger("echo.modules.publishing")

#: Statuses from which a draft may be published.
PUBLISHABLE_STATUSES = ("approved", "ready")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def publish_approved(
    db: Session,
    approval_id: str,
    *,
    connector: str = "noop",
    actor: str = "operator",
    dry_run: bool | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """Publish an approved draft through a connector, behind the hard guard.

    Returns a result dict; raises LookupError if the approval is missing and
    PermissionError if the approval gate is not satisfied.
    """
    approval = db.query(Approval).filter(Approval.id == approval_id).first()
    if approval is None:
        raise LookupError(f"Approval {approval_id} not found")

    # ── Gate 1: approval must be approved/ready ───────────────────────────────
    if approval.status not in PUBLISHABLE_STATUSES:
        raise PermissionError(
            f"Cannot publish: approval is '{approval.status}', "
            f"must be one of {PUBLISHABLE_STATUSES}"
        )

    conn = connectors.get_connector(connector)
    if conn is None:
        raise ValueError(
            f"Unknown connector '{connector}'. Available: {connectors.available_connectors()}"
        )

    # ── Gate 2: live only if the kill-switch is on AND caller didn't force dry-run.
    # The default (dry_run=None) resolves to: live iff ECHO_ALLOW_LIVE_PUBLISH.
    if dry_run is None:
        effective_dry_run = not ECHO_ALLOW_LIVE_PUBLISH
    else:
        effective_dry_run = dry_run or not ECHO_ALLOW_LIVE_PUBLISH

    # Resolve content from the linked ContentItem, else the draft body.
    content: dict[str, Any] = {"body": approval.draft_content or "",
                               "caption": approval.draft_content or ""}
    item = None
    if approval.content_post_id:
        item = (
            db.query(ContentItem)
            .filter(ContentItem.post_id == approval.content_post_id)
            .first()
        )
        if item is not None:
            content["caption"] = item.caption or content["caption"]
            if item.cta_url:
                content["url"] = item.cta_url
            if item.image_url:
                content["image_url"] = item.image_url

    result = conn.send(content, dry_run=effective_dry_run)
    went_live = result.success and not result.dry_run

    # Advance the linked content item only on a real live publish.
    if item is not None and went_live:
        item.published = True
        item.published_url = result.live_url
        item.published_at = _utcnow()
        item.status = "published"
        item.updated_at = _utcnow()

    # Analytics: mark ready/published (this is the "shipped" signal).
    events.record_event(
        db,
        events.EVENT_DRAFT_PUBLISHED_OR_READY,
        workflow_id=(approval.resume_payload or {}).get("workflow_id"),
        workflow_run_id=approval.run_id,
        user_id=actor,
        tenant_id=tenant_id,
        metadata={
            "approval_id": approval.id,
            "connector": connector,
            "dry_run": result.dry_run,
            "went_live": went_live,
            "live_publish_enabled": ECHO_ALLOW_LIVE_PUBLISH,
        },
    )
    db.commit()

    return {
        "approval_id": approval.id,
        "connector": connector,
        "dry_run": result.dry_run,
        "went_live": went_live,
        "success": result.success,
        "live_url": result.live_url,
        "live_publish_enabled": ECHO_ALLOW_LIVE_PUBLISH,
        "detail": result.detail,
        "error": result.error,
    }
