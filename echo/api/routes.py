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


@router.get("/db-health")
def db_health() -> dict:
    """Non-authenticated DB connectivity check — safe to expose (no data returned)."""
    from echo.config import DATABASE_URL as _db_url
    from echo.db import engine, ensure_tables

    # Mask the URL: show scheme + host only, never the password
    try:
        from urllib.parse import urlparse
        parsed = urlparse(_db_url)
        safe_url = f"{parsed.scheme}://{parsed.hostname}:{parsed.port or ''}/{parsed.path.lstrip('/')}"
    except Exception:
        safe_url = "(unparseable)"

    # Try to ensure tables are created
    init_error: str | None = None
    try:
        ensure_tables()
    except Exception as exc:
        init_error = str(exc)

    # Try a lightweight connectivity check
    connect_error: str | None = None
    echo_tables: list[str] = []
    try:
        with engine.connect() as conn:
            result = conn.execute(
                __import__("sqlalchemy").text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_name LIKE 'echo%'"
                    " ORDER BY table_name"
                    if not _db_url.startswith("sqlite")
                    else "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'echo%' ORDER BY name"
                )
            )
            echo_tables = [row[0] for row in result]
    except Exception as exc:
        connect_error = str(exc)

    return {
        "db_url_safe": safe_url,
        "db_reachable": connect_error is None,
        "echo_tables": echo_tables,
        "init_error": init_error,
        "connect_error": connect_error,
    }


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
    if get_workflow(slug) is None:
        raise HTTPException(status_code=404, detail=f"Workflow '{slug}' not found")

    try:
        run, result = run_workflow(db, slug, body.payload, triggered_by=body.triggered_by)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return {
        "run_id": str(run.id),
        "slug": run.workflow_slug,
        "status": run.status,
        "result": run.result,
        "message": result.message,
        "error": run.error,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "finished_at": run.updated_at.isoformat() if run.updated_at else None,
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
                "finished_at": r.updated_at.isoformat() if r.updated_at else None,
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
        "finished_at": run.updated_at.isoformat() if run.updated_at else None,
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
                "post_id": i.post_id,
                "title": i.title,
                "brand": i.brand,
                "workflow": i.workflow,
                "content_type": i.content_type,
                "status": i.status,
                "approved": i.approved,
                "published": i.published,
                "published_url": i.published_url,
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
                "job_id": j.job_id,
                "post_id": j.post_id,
                "platform": j.platform,
                "status": j.status,
                "scheduling_mode": j.scheduling_mode,
                "attempt_count": j.attempt_count,
                "external_post_id": j.external_post_id,
                "published_url": j.published_url,
                "error_message": j.error_message,
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
    run_id: str | None = Query(None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """List automation log entries."""
    q = db.query(AutomationLog)
    if level:
        q = q.filter(AutomationLog.level == level)
    if run_id:
        q = q.filter(AutomationLog.run_id == run_id)
    total = q.count()
    logs = q.order_by(AutomationLog.created_at.desc()).offset(offset).limit(limit).all()
    return {
        "logs": [
            {
                "id": str(l.id),
                "level": l.level,
                "message": l.message,
                "workflow": l.workflow,
                "step": l.step,
                "run_id": l.run_id,
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
    records = db.query(IntegrationHealth).order_by(IntegrationHealth.id.desc()).all()
    return {
        "integrations": [
            {
                "id": str(r.id),
                "integration": r.integration,
                "status": r.status,
                "credential_name": r.credential_name,
                "error_message": r.error_message,
                "notes": r.notes,
                "last_checked": r.last_checked.isoformat() if r.last_checked else None,
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


# ─── Echo Job Control Panel ───────────────────────────────────────────────────

from echo.api.echo_routes import router as echo_router  # noqa: E402
router.include_router(echo_router, prefix="/echo")


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
    if get_workflow(slug) is None:
        raise HTTPException(status_code=404, detail=f"Workflow '{slug}' not found")

    try:
        run, result = run_workflow(db, slug, body, triggered_by="webhook")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return {
        "run_id": str(run.id),
        "slug": run.workflow_slug,
        "status": run.status,
        "result": run.result,
        "message": result.message,
        "error": run.error,
        "triggered_by": "webhook",
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "finished_at": run.updated_at.isoformat() if run.updated_at else None,
    }
