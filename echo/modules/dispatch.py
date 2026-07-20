"""Send an approved Echo GovCon draft out through its live connector.

Closes the loop between the approval queue and the connectors: `mark_ready`
signals a draft has cleared review; this module performs the actual send when an
operator explicitly triggers it (``POST /approvals/{id}/send``). It routes by the
approval's ``draft_type``:

    linkedin_post → LinkedIn   (echo.integrations.linkedin, via publisher)
    email         → Resend     (echo.integrations.email_resend, via publisher)

Everything stays behind the publish gate: unless ``ECHO_ALLOW_LIVE_PUBLISH=true``
(and the connector is configured) the send is a labelled dry-run. A send records
a publishing job for the cockpit and a ``draft_published_or_marked_ready``
analytics event, and advances the approval to ``sent``. Briefs/alerts are
internal artifacts and are not directly sendable through this bridge.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from echo.core.logger import get_logger
from echo.db import Approval
from echo.modules import events
from echo.modules.content_store import get_content_by_post_id, record_publishing_job
from echo.modules.publisher import publish

log = get_logger("echo.modules.dispatch")

#: draft_type → the publisher platform it sends through.
_DRAFT_TYPE_PLATFORM = {
    "linkedin_post": "linkedin",
    "email": "email",
}

#: draft_types that are internal reports, not outbound sends.
_NON_SENDABLE = ("brief", "alert", "handoff")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class DispatchError(Exception):
    """Raised for caller errors (bad status / type / missing recipient)."""

    message: str
    status_code: int = 409

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.message


def sendable_platform(draft_type: str | None) -> str | None:
    """Return the platform an approved draft of this type sends to, or None."""
    return _DRAFT_TYPE_PLATFORM.get(draft_type or "")


def _build_content(approval: Approval, db: Session, *, recipient: str | None,
                   subject: str | None) -> tuple[str, dict[str, Any]]:
    """Resolve (platform, content) for a draft, or raise DispatchError."""
    draft_type = approval.draft_type
    platform = sendable_platform(draft_type)
    if platform is None:
        if draft_type in _NON_SENDABLE:
            raise DispatchError(
                f"draft_type '{draft_type}' is an internal report, not a sendable "
                f"message (sendable types: {', '.join(_DRAFT_TYPE_PLATFORM)})",
                status_code=422,
            )
        raise DispatchError(
            f"draft_type '{draft_type}' has no configured connector", status_code=422
        )

    body = approval.draft_content or ""

    # Pull the UTM-tagged CTA link from the linked ContentItem, if any.
    cta_url = None
    if approval.content_post_id:
        item = get_content_by_post_id(db, approval.content_post_id)
        if item is not None and item.cta_url:
            cta_url = item.cta_url

    if platform == "linkedin":
        content: dict[str, Any] = {"body": body}
        if cta_url:
            content["url"] = cta_url
        return platform, content

    # email
    if not recipient:
        raise DispatchError("email drafts require a 'recipient' address", status_code=422)
    subject = subject or _derive_subject(body)
    return platform, {"to": recipient, "subject": subject, "text": body}


def _derive_subject(body: str) -> str:
    """First non-empty line of the draft (stripped of markdown heading marks)."""
    for line in body.splitlines():
        line = line.strip().lstrip("#").strip()
        if line:
            return line[:120]
    return "A message from Echo GovCon"


def send_ready_draft(
    db: Session,
    approval_id: str,
    *,
    sent_by: str,
    recipient: str | None = None,
    subject: str | None = None,
    tenant_id: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Send an approved/ready draft via its connector. Returns a result dict.

    The draft must be ``approved`` or ``ready``. Publishing is forced to dry-run
    unless ``ECHO_ALLOW_LIVE_PUBLISH`` is enabled (the publisher enforces this).
    """
    approval = db.query(Approval).filter(Approval.id == approval_id).first()
    if approval is None:
        raise DispatchError(f"Approval {approval_id} not found", status_code=404)
    if approval.status not in ("approved", "ready"):
        raise DispatchError(
            f"Only approved/ready drafts can be sent (status is {approval.status})",
            status_code=409,
        )

    platform, content = _build_content(approval, db, recipient=recipient, subject=subject)

    result = publish(platform, content, dry_run=dry_run)

    job = record_publishing_job(
        db,
        post_id=approval.content_post_id,
        platform=platform,
        status="dry_run" if result.dry_run else ("published" if result.success else "failed"),
        published_url=result.live_url,
        external_post_id=result.live_url,
        error_message=result.error,
    )

    if result.success:
        approval.status = "sent"
        approval.updated_at = _utcnow()
        db.commit()
        db.refresh(approval)
        events.record_event(
            db,
            events.EVENT_DRAFT_PUBLISHED_OR_READY,
            workflow_id=(approval.resume_payload or {}).get("workflow_id"),
            workflow_run_id=approval.run_id,
            user_id=sent_by,
            tenant_id=tenant_id,
            metadata={
                "approval_id": approval.id,
                "draft_type": approval.draft_type,
                "platform": platform,
                "dry_run": result.dry_run,
                "publishing_job_id": job.id,
            },
        )

    log.info(
        "Dispatched approval=%s platform=%s dry_run=%s success=%s",
        approval_id, platform, result.dry_run, result.success,
    )
    return {
        "approval_id": approval.id,
        "platform": platform,
        "status": approval.status,
        "dry_run": result.dry_run,
        "success": result.success,
        "publishing_job_id": job.id,
        "live_url": result.live_url,
        "error": result.error,
        "simulated_output": result.simulated_output,
    }
