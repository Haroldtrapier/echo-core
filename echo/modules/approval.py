"""Approval module — create, query, and decide on workflow approvals.

Two flavours of approval share one table:

  * **Publish-gate approvals** (``create_approval``) — legacy gate used by
    ``approved_publisher``; carries a ``resume_payload`` and no draft body.
  * **Draft approvals** (``create_draft_approval``) — the approval-first content
    model: an AI-generated draft (brief / linkedin_post / email / alert / handoff)
    that a human reviews before anything ships. Carries ``draft_type`` +
    ``draft_content`` and, on decision, records analytics events.

Every draft decision writes a ``draft_approved`` / ``draft_rejected`` analytics
event and stamps ``reviewed_by`` / ``reviewed_at``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from echo.core.logger import get_logger
from echo.db import Approval
from echo.modules import events

log = get_logger("echo.modules.approval")

#: Draft kinds the approval queue understands.
DRAFT_TYPES = ("brief", "linkedin_post", "email", "alert", "handoff")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def create_approval(
    db: Session,
    *,
    run_id: str | None,
    requested_by: str,
    reason: str | None = None,
    resume_payload: dict[str, Any] | None = None,
) -> Approval:
    """Create a publish-gate approval (no draft body)."""
    approval = Approval(
        run_id=run_id,
        requested_by=requested_by,
        reason=reason,
        resume_payload=resume_payload or {},
        status="pending",
    )
    db.add(approval)
    db.commit()
    db.refresh(approval)
    log.info("Approval created id=%s run_id=%s", approval.id, run_id)
    return approval


def create_draft_approval(
    db: Session,
    *,
    draft_type: str,
    draft_content: str,
    requested_by: str,
    run_id: str | None = None,
    reason: str | None = None,
    content_post_id: str | None = None,
    workflow_id: str | None = None,
    tenant_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Approval:
    """Create an approval-first draft and record a ``draft_created`` event.

    ``draft_type`` should be one of :data:`DRAFT_TYPES`; unknown values are
    accepted but logged, so new draft kinds don't hard-fail the loop.
    """
    if draft_type not in DRAFT_TYPES:
        log.warning("Unknown draft_type %r (allowed: %s)", draft_type, DRAFT_TYPES)
    approval = Approval(
        run_id=run_id,
        requested_by=requested_by,
        reason=reason or f"Review {draft_type} draft",
        status="pending",
        draft_type=draft_type,
        draft_content=draft_content,
        content_post_id=content_post_id,
        resume_payload=metadata or {},
    )
    db.add(approval)
    db.commit()
    db.refresh(approval)
    events.record_event(
        db,
        events.EVENT_DRAFT_CREATED,
        workflow_id=workflow_id,
        workflow_run_id=run_id,
        user_id=requested_by,
        tenant_id=tenant_id,
        metadata={
            "approval_id": approval.id,
            "draft_type": draft_type,
            "content_post_id": content_post_id,
            **(metadata or {}),
        },
    )
    log.info("Draft approval created id=%s type=%s", approval.id, draft_type)
    return approval


def get_pending(db: Session, limit: int = 100) -> list[Approval]:
    return (
        db.query(Approval)
        .filter(Approval.status == "pending")
        .order_by(Approval.created_at)
        .limit(limit)
        .all()
    )


def get_approval(db: Session, approval_id: str) -> Approval | None:
    return db.query(Approval).filter(Approval.id == approval_id).first()


def decide(
    db: Session,
    approval_id: str,
    *,
    decision: str,
    decision_by: str,
    note: str | None = None,
    tenant_id: str | None = None,
    workflow_id: str | None = None,
) -> Approval:
    """Approve or reject an approval; stamp reviewer + record analytics."""
    if decision not in ("approved", "rejected"):
        raise ValueError("decision must be 'approved' or 'rejected'")
    approval = db.query(Approval).filter(Approval.id == approval_id).first()
    if approval is None:
        raise LookupError(f"Approval {approval_id} not found")
    if approval.status != "pending":
        raise ValueError(f"Approval {approval_id} is already {approval.status}")
    now = _utcnow()
    approval.status = decision
    approval.decision_by = decision_by
    approval.decision_note = note
    approval.reviewed_by = decision_by
    approval.reviewed_at = now
    approval.updated_at = now
    db.commit()
    db.refresh(approval)

    # Draft approvals emit analytics; publish-gate approvals stay silent here
    # (the publisher records its own events on the publish action).
    if approval.draft_type:
        events.record_event(
            db,
            events.EVENT_DRAFT_APPROVED if decision == "approved" else events.EVENT_DRAFT_REJECTED,
            workflow_id=workflow_id or (approval.resume_payload or {}).get("workflow_id"),
            workflow_run_id=approval.run_id,
            user_id=decision_by,
            tenant_id=tenant_id,
            metadata={
                "approval_id": approval.id,
                "draft_type": approval.draft_type,
                "content_post_id": approval.content_post_id,
                "note": note,
            },
        )
    log.info("Approval %s → %s by %s", approval_id, decision, decision_by)
    return approval


def edit_draft(db: Session, approval_id: str, *, draft_content: str) -> Approval:
    """Edit a pending draft's content in place (before decision)."""
    approval = db.query(Approval).filter(Approval.id == approval_id).first()
    if approval is None:
        raise LookupError(f"Approval {approval_id} not found")
    if approval.status != "pending":
        raise ValueError(f"Cannot edit a draft that is already {approval.status}")
    approval.draft_content = draft_content
    approval.updated_at = _utcnow()
    db.commit()
    db.refresh(approval)
    return approval


def mark_ready(
    db: Session,
    approval_id: str,
    *,
    marked_by: str,
    tenant_id: str | None = None,
    workflow_id: str | None = None,
) -> Approval:
    """Mark an approved draft as ready to publish/send.

    Records a ``draft_published_or_marked_ready`` analytics event. This does not
    itself publish — publishing stays gated behind ``approved_publisher`` /
    connector execution — it signals the draft has cleared review and is queued.
    """
    approval = db.query(Approval).filter(Approval.id == approval_id).first()
    if approval is None:
        raise LookupError(f"Approval {approval_id} not found")
    if approval.status != "approved":
        raise ValueError(
            f"Only approved drafts can be marked ready (status is {approval.status})"
        )
    approval.status = "ready"
    approval.updated_at = _utcnow()
    db.commit()
    db.refresh(approval)
    events.record_event(
        db,
        events.EVENT_DRAFT_PUBLISHED_OR_READY,
        workflow_id=workflow_id or (approval.resume_payload or {}).get("workflow_id"),
        workflow_run_id=approval.run_id,
        user_id=marked_by,
        tenant_id=tenant_id,
        metadata={
            "approval_id": approval.id,
            "draft_type": approval.draft_type,
            "content_post_id": approval.content_post_id,
        },
    )
    log.info("Approval %s marked ready by %s", approval_id, marked_by)
    return approval


def approval_dict(a: Approval) -> dict[str, Any]:
    return {
        "id": a.id,
        "run_id": a.run_id,
        "requested_by": a.requested_by,
        "reason": a.reason,
        "status": a.status,
        "draft_type": a.draft_type,
        "draft_content": a.draft_content,
        "content_post_id": a.content_post_id,
        "reviewed_by": a.reviewed_by,
        "reviewed_at": a.reviewed_at.isoformat() if a.reviewed_at else None,
        "decision_by": a.decision_by,
        "decision_note": a.decision_note,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "updated_at": a.updated_at.isoformat() if a.updated_at else None,
    }
