"""Echo Core API routes."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from echo.auth import require_api_key
from echo.core.registry import get_workflow, list_workflows
from echo.core.runner import run_workflow
from echo.db import (
    Approval,
    AutomationLog,
    ContentItem,
    IntegrationHealth,
    PublishingJob,
    WorkflowRun,
    get_db,
)
from echo.modules.analytics import get_summary
from echo.modules.approval import create_approval, decide, get_pending

router = APIRouter()


# ─── Health (unauthenticated) ────────────────────────────────────────────────


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "echo-core"}


# ─── Workflows ────────────────────────────────────────────────────────────────


@router.get("/workflows", dependencies=[Depends(require_api_key)])
def list_workflows_endpoint() -> dict[str, Any]:
    """List all registered workflows."""
    return {
        "workflows": [
            {
                "slug": wf.slug,
                "name": wf.name,
                "description": wf.description,
            }
            for wf in list_workflows()
        ],
        "count": len(list_workflows()),
    }


class RunWorkflowRequest(BaseModel):
    payload: dict[str, Any] = {}
    triggered_by: str = "api"


@router.post("/workflows/{slug}/run", dependencies=[Depends(require_api_key)])
def run_workflow_endpoint(
    slug: str,
    body: RunWorkflowRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Trigger a workflow by slug."""
    wf = get_workflow(slug)
    if wf is None:
        raise HTTPException(status_code=404, detail=f"Workflow '{slug}' not found")

    errors = wf.validate(body.payload)
    if errors:
        raise HTTPException(status_code=422, detail={"validation_errors": errors})

    run = run_workflow(db, slug, body.payload, triggered_by=body.triggered_by)
    return {
        "run_id": str(run.id),
        "slug": run.workflow_slug,
        "status": run.status,
        "result": run.result,
        "error": run.error,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


# ─── Workflow Runs ────────────────────────────────────────────────────────────


@router.get("/runs", dependencies=[Depends(require_api_key)])
def list_runs(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    slug: str | None = Query(None),
    status: str | None = Query(None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """List workflow runs with optional filtering."""
    q = db.query(WorkflowRun)
    if slug:
        q = q.filter(WorkflowRun.workflow_slug == slug)
    if status:
        q = q.filter(WorkflowRun.status == status)
    total = q.count()
    runs = q.order_by(WorkflowRun.created_at.desc()).offset(offset).limit(limit).all()
    return {
        "runs": [
            {
                "run_id": str(r.id),
                "slug": r.workflow_slug,
                "status": r.status,
                "triggered_by": r.triggered_by,
                "error": r.error,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            }
            for r in runs
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/runs/{run_id}", dependencies=[Depends(require_api_key)])
def get_run(run_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    run = db.query(WorkflowRun).filter(WorkflowRun.id == run_id).first()
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return {
        "run_id": str(run.id),
        "slug": run.workflow_slug,
        "status": run.status,
        "triggered_by": run.triggered_by,
        "payload": run.payload,
        "result": run.result,
        "error": run.error,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


# ─── Approvals ────────────────────────────────────────────────────────────────


@router.get("/approvals", dependencies=[Depends(require_api_key)])
def list_approvals(
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """List pending approvals."""
    pending = get_pending(db, limit=limit)
    return {
        "approvals": [
            {
                "id": str(a.id),
                "run_id": str(a.run_id) if a.run_id else None,
                "requested_by": a.requested_by,
                "reason": a.reason,
                "status": a.status,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in pending
        ],
        "count": len(pending),
    }


class ApprovalDecisionRequest(BaseModel):
    decision: str  # "approved" | "rejected"
    decision_by: str
    note: str | None = None


@router.post("/approvals/{approval_id}/decide", dependencies=[Depends(require_api_key)])
def decide_approval(
    approval_id: str,
    body: ApprovalDecisionRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Approve or reject a pending approval."""
    try:
        approval = decide(
            db,
            approval_id,
            decision=body.decision,
            decision_by=body.decision_by,
            note=body.note,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "id": str(approval.id),
        "status": approval.status,
        "decision_by": approval.decision_by,
        "decision_note": approval.decision_note,
        "updated_at": approval.updated_at.isoformat() if approval.updated_at else None,
    }


# ─── Content (cockpit read model) ─────────────────────────────────────────────


@router.get("/content", dependencies=[Depends(require_api_key)])
def list_content(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status: str | None = Query(None),
    published: bool | None = Query(None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """List content items."""
    q = db.query(ContentItem)
    if status:
        q = q.filter(ContentItem.status == status)
    if published is not None:
        q = q.filter(ContentItem.published == published)
    total = q.count()
    items = q.order_by(ContentItem.created_at.desc()).offset(offset).limit(limit).all()
    return {
        "items": [
            {
                "id": str(i.id),
                "title": i.title,
                "platform": i.platform,
                "status": i.status,
                "published": i.published,
                "workflow_run_id": str(i.workflow_run_id) if i.workflow_run_id else None,
                "created_at": i.created_at.isoformat() if i.created_at else None,
                "updated_at": i.updated_at.isoformat() if i.updated_at else None,
            }
            for i in items
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


# ─── Publishing Jobs ──────────────────────────────────────────────────────────


@router.get("/publishing-jobs", dependencies=[Depends(require_api_key)])
def list_publishing_jobs(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status: str | None = Query(None),
    platform: str | None = Query(None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """List publishing jobs."""
    q = db.query(PublishingJob)
    if status:
        q = q.filter(PublishingJob.status == status)
    if platform:
        q = q.filter(PublishingJob.platform == platform)
    total = q.count()
    jobs = q.order_by(PublishingJob.created_at.desc()).offset(offset).limit(limit).all()
    return {
        "jobs": [
            {
                "id": str(j.id),
                "platform": j.platform,
                "status": j.status,
                "dry_run": j.dry_run,
                "live_url": j.live_url,
                "error": j.error,
                "workflow_run_id": str(j.workflow_run_id) if j.workflow_run_id else None,
                "created_at": j.created_at.isoformat() if j.created_at else None,
            }
            for j in jobs
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


# ─── Logs ─────────────────────────────────────────────────────────────────────


@router.get("/logs", dependencies=[Depends(require_api_key)])
def list_logs(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    level: str | None = Query(None),
    workflow_run_id: str | None = Query(None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """List automation log entries."""
    q = db.query(AutomationLog)
    if level:
        q = q.filter(AutomationLog.level == level)
    if workflow_run_id:
        q = q.filter(AutomationLog.workflow_run_id == workflow_run_id)
    total = q.count()
    logs = q.order_by(AutomationLog.created_at.desc()).offset(offset).limit(limit).all()
    return {
        "logs": [
            {
                "id": str(l.id),
                "level": l.level,
                "message": l.message,
                "source": l.source,
                "workflow_run_id": str(l.workflow_run_id) if l.workflow_run_id else None,
                "created_at": l.created_at.isoformat() if l.created_at else None,
            }
            for l in logs
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


# ─── Integration Health ───────────────────────────────────────────────────────


@router.get("/integration-health", dependencies=[Depends(require_api_key)])
def list_integration_health(db: Session = Depends(get_db)) -> dict[str, Any]:
    """List integration health status records."""
    records = db.query(IntegrationHealth).order_by(IntegrationHealth.checked_at.desc()).all()
    return {
        "integrations": [
            {
                "id": str(r.id),
                "integration_name": r.integration_name,
                "status": r.status,
                "details": r.details,
                "checked_at": r.checked_at.isoformat() if r.checked_at else None,
            }
            for r in records
        ],
        "count": len(records),
    }


# ─── Analytics Summary ────────────────────────────────────────────────────────


@router.get("/analytics/summary", dependencies=[Depends(require_api_key)])
def analytics_summary(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Aggregate analytics summary."""
    return get_summary(db)


# ─── Webhooks ─────────────────────────────────────────────────────────────────


@router.post("/webhooks/{slug}", dependencies=[Depends(require_api_key)])
def webhook_trigger(
    slug: str,
    body: dict[str, Any],
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Accept an external webhook payload and trigger the matching workflow.

    Designed for external integrations (e.g. SAM.gov alerts, FEMA feeds, CMS
    callbacks) that POST structured payloads.  The full request body is passed
    as-is to the workflow's ``run()`` method so each workflow controls its own
    payload contract.

    Returns immediately with the run_id and initial status — the workflow
    executes synchronously within this request.
    """
    wf = get_workflow(slug)
    if wf is None:
        raise HTTPException(status_code=404, detail=f"Workflow '{slug}' not found")

    errors = wf.validate(body)
    if errors:
        raise HTTPException(status_code=422, detail={"validation_errors": errors})

    run = run_workflow(db, slug, body, triggered_by="webhook")
    return {
        "run_id": str(run.id),
        "slug": run.workflow_slug,
        "status": run.status,
        "result": run.result,
        "error": run.error,
        "triggered_by": "webhook",
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }
