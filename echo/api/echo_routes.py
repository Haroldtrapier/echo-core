"""Echo job control-panel routes.

Mounted at /api/v1/echo by routes.py — all endpoints require x-echo-key auth.

Paths (relative to /echo):
  GET  /status                          → EchoStatus
  GET  /jobs                            → EchoJob[]
  POST /jobs                            → EchoJob
  GET  /jobs/{id}                       → EchoJob
  POST /jobs/{id}/dry-run               → EchoJob
  POST /jobs/{id}/request-approval      → EchoJob
  POST /jobs/{id}/execute               → EchoJob  (gated: approval + live publish)
  GET  /jobs/{id}/execution-audit       → EchoExecutionAudit[]
  POST /jobs/{id}/schedule              → EchoJobSchedule
  GET  /jobs/{id}/schedules             → EchoJobSchedule[]
  GET  /schedules                       → EchoJobSchedule[]
  POST /schedules/{sid}/cancel          → EchoJobSchedule
  PATCH /schedules/{sid}                → EchoJobSchedule
  POST /scheduler/tick                  → EchoTickReport
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from echo.auth import require_api_key
from echo.config import ECHO_ALLOW_LIVE_PUBLISH, ECHO_ENABLED
from echo.db import (
    Approval,
    EchoExecutionAudit,
    EchoJob,
    EchoJobSchedule,
    get_db,
)

router = APIRouter()

SUPPORTED_CHANNELS = ["linkedin", "x", "email", "slack"]


# ── helpers ───────────────────────────────────────────────────────────────────


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _job_dict(j: EchoJob) -> dict[str, Any]:
    return {
        "id": j.id,
        "tenant_id": j.tenant_id,
        "created_by": j.created_by,
        "title": j.title,
        "channel": j.channel,
        "body": j.body,
        "subject": j.subject,
        "job_metadata": j.job_metadata,
        "status": j.status,
        "approval_id": j.approval_id,
        "dry_run_result": j.dry_run_result,
        "created_at": j.created_at.isoformat() if j.created_at else None,
        "updated_at": j.updated_at.isoformat() if j.updated_at else None,
    }


def _schedule_dict(s: EchoJobSchedule) -> dict[str, Any]:
    return {
        "id": s.id,
        "tenant_id": s.tenant_id,
        "echo_job_id": s.echo_job_id,
        "created_by": s.created_by,
        "scheduled_for": s.scheduled_for.isoformat() if s.scheduled_for else None,
        "status": s.status,
        "run_count": s.run_count,
        "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
        "last_result": s.last_result,
        "error": s.error,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


def _audit_dict(a: EchoExecutionAudit) -> dict[str, Any]:
    return {
        "id": a.id,
        "tenant_id": a.tenant_id,
        "echo_job_id": a.echo_job_id,
        "approval_id": a.approval_id,
        "workflow_run_id": a.workflow_run_id,
        "attempted_by": a.attempted_by,
        "action": a.action,
        "result": a.result,
        "approval_status": a.approval_status,
        "live_publish_enabled": a.live_publish_enabled,
        "reason": a.reason,
        "request_metadata": a.request_metadata,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


def _get_job_or_404(db: Session, job_id: str) -> EchoJob:
    job = db.query(EchoJob).filter(EchoJob.id == job_id).first()
    if job is None:
        raise HTTPException(status_code=404, detail=f"Echo job {job_id} not found")
    return job


def _record_audit(
    db: Session,
    *,
    job: EchoJob,
    action: str,
    result: str,
    reason: str | None = None,
    approval_status: str | None = None,
) -> None:
    audit = EchoExecutionAudit(
        tenant_id=job.tenant_id,
        echo_job_id=job.id,
        approval_id=job.approval_id,
        attempted_by=job.created_by,
        action=action,
        result=result,
        approval_status=approval_status,
        live_publish_enabled=ECHO_ALLOW_LIVE_PUBLISH,
        reason=reason,
    )
    db.add(audit)
    db.flush()


def _simulate_dry_run(job: EchoJob) -> dict[str, Any]:
    """Return a simulated dry-run result without touching any external API."""
    preview = job.body[:120] + ("…" if len(job.body) > 120 else "")
    return {
        "simulated": True,
        "channel": job.channel,
        "title": job.title,
        "preview": preview,
        "would_post_to": f"https://{job.channel}.com/imani-apex (dry-run)",
        "live_publish_enabled": ECHO_ALLOW_LIVE_PUBLISH,
        "note": "No external API was called. Enable ECHO_ALLOW_LIVE_PUBLISH to unlock live publishing.",
    }


# ── Status ────────────────────────────────────────────────────────────────────


@router.get("/status", dependencies=[Depends(require_api_key)])
def echo_status() -> dict[str, Any]:
    return {
        "enabled": ECHO_ENABLED,
        "live_publishing_enabled": ECHO_ALLOW_LIVE_PUBLISH,
        "supported_channels": SUPPORTED_CHANNELS,
    }


# ── Jobs CRUD ─────────────────────────────────────────────────────────────────


class EchoJobInput(BaseModel):
    title: str
    channel: str = "linkedin"
    body: str
    subject: str | None = None
    job_metadata: dict[str, Any] | None = None


@router.get("/jobs", dependencies=[Depends(require_api_key)])
def list_jobs(
    status: str | None = Query(None),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    q = db.query(EchoJob)
    if status:
        q = q.filter(EchoJob.status == status)
    return [_job_dict(j) for j in q.order_by(EchoJob.created_at.desc()).all()]


@router.post("/jobs", dependencies=[Depends(require_api_key)])
def create_job(body: EchoJobInput, db: Session = Depends(get_db)) -> dict[str, Any]:
    if body.channel not in SUPPORTED_CHANNELS:
        raise HTTPException(
            status_code=422, detail=f"Unsupported channel '{body.channel}'. Choose from {SUPPORTED_CHANNELS}"
        )
    job = EchoJob(
        title=body.title,
        channel=body.channel,
        body=body.body,
        subject=body.subject,
        job_metadata=body.job_metadata,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return _job_dict(job)


@router.get("/jobs/{job_id}", dependencies=[Depends(require_api_key)])
def get_job(job_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    return _job_dict(_get_job_or_404(db, job_id))


# ── Job actions ───────────────────────────────────────────────────────────────


@router.post("/jobs/{job_id}/dry-run", dependencies=[Depends(require_api_key)])
def dry_run_job(job_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    job = _get_job_or_404(db, job_id)
    if job.status not in ("draft", "dry_run"):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot dry-run a job with status '{job.status}'",
        )
    job.dry_run_result = _simulate_dry_run(job)
    job.status = "dry_run"
    _record_audit(db, job=job, action="dry_run", result="allowed_unimplemented",
                  reason="Dry-run completed — no live API called.")
    db.commit()
    db.refresh(job)
    return _job_dict(job)


class ApprovalRequest(BaseModel):
    reason: str | None = None


@router.post("/jobs/{job_id}/request-approval", dependencies=[Depends(require_api_key)])
def request_approval(job_id: str, body: ApprovalRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    job = _get_job_or_404(db, job_id)
    if job.status != "dry_run":
        raise HTTPException(
            status_code=409,
            detail="Approval can only be requested after a successful dry-run.",
        )
    # Create an Approval record and link it to the job.
    approval = Approval(
        requested_by=job.created_by,
        reason=body.reason or f"Approve Echo job: {job.title}",
    )
    db.add(approval)
    db.flush()
    job.approval_id = approval.id
    job.status = "pending_approval"
    db.commit()
    db.refresh(job)
    return _job_dict(job)


@router.post("/jobs/{job_id}/execute", dependencies=[Depends(require_api_key)])
def execute_job(job_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Gated execution — blocked unless an approved approval AND live publish is on."""
    job = _get_job_or_404(db, job_id)

    # Resolve approval status
    approval_status: str | None = None
    if job.approval_id:
        approval = db.query(Approval).filter(Approval.id == job.approval_id).first()
        approval_status = approval.status if approval else None

    # Gate 1: approval required
    if approval_status != "approved":
        _record_audit(
            db, job=job, action="execute",
            result="blocked_no_approval" if not approval_status else "blocked_rejected_approval",
            reason="Execution blocked: no approved Imani approval.",
            approval_status=approval_status,
        )
        db.commit()
        raise HTTPException(
            status_code=403,
            detail="Execution blocked: requires an approved Imani approval.",
        )

    # Gate 2: live publishing enabled
    if not ECHO_ALLOW_LIVE_PUBLISH:
        _record_audit(
            db, job=job, action="execute",
            result="blocked_live_disabled",
            reason="Execution blocked: ECHO_ALLOW_LIVE_PUBLISH is not enabled.",
            approval_status=approval_status,
        )
        db.commit()
        raise HTTPException(
            status_code=403,
            detail="Execution blocked: live publishing is disabled (ECHO_ALLOW_LIVE_PUBLISH=false).",
        )

    # Both gates passed — update status
    job.status = "approved"
    _record_audit(
        db, job=job, action="execute",
        result="allowed_unimplemented",
        reason="Execution allowed. Live publishing not yet wired — marking approved.",
        approval_status=approval_status,
    )
    db.commit()
    db.refresh(job)
    return _job_dict(job)


# ── Execution audit ───────────────────────────────────────────────────────────


@router.get("/jobs/{job_id}/execution-audit", dependencies=[Depends(require_api_key)])
def job_execution_audit(job_id: str, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    _get_job_or_404(db, job_id)
    audits = (
        db.query(EchoExecutionAudit)
        .filter(EchoExecutionAudit.echo_job_id == job_id)
        .order_by(EchoExecutionAudit.created_at.desc())
        .all()
    )
    return [_audit_dict(a) for a in audits]


# ── Schedules ─────────────────────────────────────────────────────────────────


class ScheduleInput(BaseModel):
    scheduled_for: str  # ISO-8601 UTC string


@router.post("/jobs/{job_id}/schedule", dependencies=[Depends(require_api_key)])
def schedule_job(job_id: str, body: ScheduleInput, db: Session = Depends(get_db)) -> dict[str, Any]:
    job = _get_job_or_404(db, job_id)
    if job.status not in ("draft", "dry_run"):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot schedule a job with status '{job.status}'",
        )
    try:
        scheduled_for = datetime.fromisoformat(body.scheduled_for.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=422, detail="scheduled_for must be an ISO-8601 datetime string")

    schedule = EchoJobSchedule(
        tenant_id=job.tenant_id,
        echo_job_id=job.id,
        created_by=job.created_by,
        scheduled_for=scheduled_for,
    )
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return _schedule_dict(schedule)


@router.get("/jobs/{job_id}/schedules", dependencies=[Depends(require_api_key)])
def list_job_schedules(job_id: str, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    _get_job_or_404(db, job_id)
    rows = (
        db.query(EchoJobSchedule)
        .filter(EchoJobSchedule.echo_job_id == job_id)
        .order_by(EchoJobSchedule.scheduled_for.asc())
        .all()
    )
    return [_schedule_dict(s) for s in rows]


@router.get("/schedules", dependencies=[Depends(require_api_key)])
def list_schedules(
    status: str | None = Query(None),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    q = db.query(EchoJobSchedule)
    if status:
        q = q.filter(EchoJobSchedule.status == status)
    return [_schedule_dict(s) for s in q.order_by(EchoJobSchedule.scheduled_for.asc()).all()]


@router.post("/schedules/{schedule_id}/cancel", dependencies=[Depends(require_api_key)])
def cancel_schedule(schedule_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    s = db.query(EchoJobSchedule).filter(EchoJobSchedule.id == schedule_id).first()
    if s is None:
        raise HTTPException(status_code=404, detail=f"Schedule {schedule_id} not found")
    if s.status != "pending":
        raise HTTPException(status_code=409, detail=f"Cannot cancel a schedule with status '{s.status}'")
    s.status = "canceled"
    db.commit()
    db.refresh(s)
    return _schedule_dict(s)


class RescheduleInput(BaseModel):
    scheduled_for: str


@router.patch("/schedules/{schedule_id}", dependencies=[Depends(require_api_key)])
def reschedule(schedule_id: str, body: RescheduleInput, db: Session = Depends(get_db)) -> dict[str, Any]:
    s = db.query(EchoJobSchedule).filter(EchoJobSchedule.id == schedule_id).first()
    if s is None:
        raise HTTPException(status_code=404, detail=f"Schedule {schedule_id} not found")
    if s.status != "pending":
        raise HTTPException(status_code=409, detail=f"Cannot reschedule a schedule with status '{s.status}'")
    try:
        s.scheduled_for = datetime.fromisoformat(body.scheduled_for.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=422, detail="scheduled_for must be an ISO-8601 datetime string")
    db.commit()
    db.refresh(s)
    return _schedule_dict(s)


# ── Scheduler tick ────────────────────────────────────────────────────────────


@router.post("/scheduler/tick", dependencies=[Depends(require_api_key)])
def scheduler_tick(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Run all pending schedules that are due now. Each fires a dry-run."""
    now = _utcnow()
    started_at = now.isoformat()

    due: list[EchoJobSchedule] = (
        db.query(EchoJobSchedule)
        .filter(
            EchoJobSchedule.status == "pending",
            EchoJobSchedule.scheduled_for <= now,
        )
        .all()
    )

    completed: list[str] = []
    failed: list[dict[str, Any]] = []

    for s in due:
        job = db.query(EchoJob).filter(EchoJob.id == s.echo_job_id).first()
        if job is None:
            s.status = "failed"
            s.error = "Job not found"
            failed.append({"schedule_id": s.id, "error": "Job not found"})
            continue
        try:
            # Perform a dry-run and update the job
            job.dry_run_result = _simulate_dry_run(job)
            if job.status == "draft":
                job.status = "dry_run"

            # Update schedule
            s.status = "completed"
            s.run_count += 1
            s.last_run_at = now
            s.last_result = job.dry_run_result
            completed.append(s.id)
        except Exception as exc:  # noqa: BLE001
            s.status = "failed"
            s.error = str(exc)
            s.run_count += 1
            s.last_run_at = now
            failed.append({"schedule_id": s.id, "error": str(exc)})

    db.commit()

    return {
        "started_at": started_at,
        "due_found": len(due),
        "completed": completed,
        "failed": failed,
        "tenant_scoped": False,
        "live_publish_enabled": ECHO_ALLOW_LIVE_PUBLISH,
    }
