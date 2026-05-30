"""Approval module — create, query, and decide on workflow approvals."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from echo.core.logger import get_logger
from echo.db import Approval

log = get_logger("echo.modules.approval")


def create_approval(
    db: Session,
    *,
    run_id: str | None,
    requested_by: str,
    reason: str | None = None,
    resume_payload: dict[str, Any] | None = None,
) -> Approval:
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


def get_pending(db: Session, limit: int = 100) -> list[Approval]:
    return (
        db.query(Approval)
        .filter(Approval.status == "pending")
        .order_by(Approval.created_at)
        .limit(limit)
        .all()
    )


def decide(
    db: Session,
    approval_id: str,
    *,
    decision: str,
    decision_by: str,
    note: str | None = None,
) -> Approval:
    if decision not in ("approved", "rejected"):
        raise ValueError("decision must be 'approved' or 'rejected'")
    approval = db.query(Approval).filter(Approval.id == approval_id).first()
    if approval is None:
        raise LookupError(f"Approval {approval_id} not found")
    if approval.status != "pending":
        raise ValueError(f"Approval {approval_id} is already {approval.status}")
    approval.status = decision
    approval.decision_by = decision_by
    approval.decision_note = note
    approval.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(approval)
    log.info("Approval %s → %s by %s", approval_id, decision, decision_by)
    return approval
