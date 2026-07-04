"""Echo GovCon API — approval queue, Sturgeon handoff, analytics events, registry.

Mounted at /api/v1/govcon by routes.py. All endpoints require the Echo API key.

Approval queue (approval-first content model):
  GET   /approvals                     → pending drafts (rich: draft_type/content/source)
  GET   /approvals/{id}                → one draft
  PATCH /approvals/{id}                → edit draft_content (while pending)
  POST  /approvals/{id}/approve        → approve  (records draft_approved)
  POST  /approvals/{id}/reject         → reject   (records draft_rejected)
  POST  /approvals/{id}/mark-ready     → mark approved draft ready to publish/send

Sturgeon handoff:
  POST  /sturgeon/handoff              → create (+ forward if configured)
  GET   /sturgeon/handoffs             → list
  GET   /sturgeon/handoffs/{id}        → one

Analytics + registry:
  GET   /analytics/events              → event stream (filterable)
  GET   /workflows/registry            → workflow registry metadata
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from echo.auth import require_api_key
from echo.config import DEFAULT_TENANT_ID
from echo.core.registry import all_metadata
from echo.db import Approval, EchoSturgeonHandoff, get_db
from echo.modules import approval as approval_mod
from echo.modules import connectors as connectors_mod
from echo.modules import conversion as conversion_mod
from echo.modules import events as events_mod
from echo.modules import publishing as publishing_mod
from echo.modules import sturgeon as sturgeon_mod

router = APIRouter()


# ─── Approval queue ───────────────────────────────────────────────────────────


@router.get("/approvals", dependencies=[Depends(require_api_key)])
def list_draft_approvals(
    status: str = Query("pending"),
    drafts_only: bool = Query(True),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    q = db.query(Approval)
    if status != "all":
        q = q.filter(Approval.status == status)
    if drafts_only:
        q = q.filter(Approval.draft_type.isnot(None))
    total = q.count()
    rows = q.order_by(Approval.created_at.desc()).offset(offset).limit(limit).all()
    return {
        "approvals": [approval_mod.approval_dict(a) for a in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/approvals/{approval_id}", dependencies=[Depends(require_api_key)])
def get_draft_approval(approval_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    a = approval_mod.get_approval(db, approval_id)
    if a is None:
        raise HTTPException(status_code=404, detail=f"Approval {approval_id} not found")
    return approval_mod.approval_dict(a)


class EditDraftRequest(BaseModel):
    draft_content: str


@router.patch("/approvals/{approval_id}", dependencies=[Depends(require_api_key)])
def edit_draft(
    approval_id: str, body: EditDraftRequest, db: Session = Depends(get_db)
) -> dict[str, Any]:
    try:
        a = approval_mod.edit_draft(db, approval_id, draft_content=body.draft_content)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return approval_mod.approval_dict(a)


class ReviewRequest(BaseModel):
    reviewed_by: str
    note: str | None = None
    tenant_id: str | None = None


@router.post("/approvals/{approval_id}/approve", dependencies=[Depends(require_api_key)])
def approve_draft(
    approval_id: str, body: ReviewRequest, db: Session = Depends(get_db)
) -> dict[str, Any]:
    return _decide(db, approval_id, "approved", body)


@router.post("/approvals/{approval_id}/reject", dependencies=[Depends(require_api_key)])
def reject_draft(
    approval_id: str, body: ReviewRequest, db: Session = Depends(get_db)
) -> dict[str, Any]:
    return _decide(db, approval_id, "rejected", body)


def _decide(db: Session, approval_id: str, decision: str, body: ReviewRequest) -> dict[str, Any]:
    try:
        a = approval_mod.decide(
            db, approval_id, decision=decision, decision_by=body.reviewed_by,
            note=body.note, tenant_id=body.tenant_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return approval_mod.approval_dict(a)


class MarkReadyRequest(BaseModel):
    marked_by: str
    tenant_id: str | None = None


@router.post("/approvals/{approval_id}/mark-ready", dependencies=[Depends(require_api_key)])
def mark_ready(
    approval_id: str, body: MarkReadyRequest, db: Session = Depends(get_db)
) -> dict[str, Any]:
    try:
        a = approval_mod.mark_ready(
            db, approval_id, marked_by=body.marked_by, tenant_id=body.tenant_id
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return approval_mod.approval_dict(a)


# ─── Sturgeon handoff ─────────────────────────────────────────────────────────


class HandoffRequest(BaseModel):
    opportunity_title: str
    agency: str | None = None
    solicitation_number: str | None = None
    due_date: str | None = None
    source_url: str | None = None
    summary: str | None = None
    requirements: str | None = None
    recommended_next_action: str | None = None
    tenant_id: str | None = None
    approval_id: str | None = None
    workflow_run_id: str | None = None
    created_by: str | None = None


@router.post("/sturgeon/handoff", dependencies=[Depends(require_api_key)])
def create_handoff(body: HandoffRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    h = sturgeon_mod.create_handoff(
        db,
        opportunity_title=body.opportunity_title,
        agency=body.agency,
        solicitation_number=body.solicitation_number,
        due_date=body.due_date,
        source_url=body.source_url,
        summary=body.summary,
        requirements=body.requirements,
        recommended_next_action=body.recommended_next_action,
        tenant_id=body.tenant_id or DEFAULT_TENANT_ID,
        approval_id=body.approval_id,
        workflow_run_id=body.workflow_run_id,
        created_by=body.created_by or "govcon_command_center",
    )
    # Record a Sturgeon-handoff *conversion* (analytics + GA4 no-op) alongside the
    # handoff's own creation event — this is the conversion-tracking signal.
    conversion_mod.track_sturgeon_handoff(db, h, tenant_id=body.tenant_id or DEFAULT_TENANT_ID)
    return sturgeon_mod.handoff_dict(h)


@router.get("/sturgeon/handoffs", dependencies=[Depends(require_api_key)])
def list_handoffs(
    status: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    q = db.query(EchoSturgeonHandoff)
    if status:
        q = q.filter(EchoSturgeonHandoff.status == status)
    total = q.count()
    rows = q.order_by(EchoSturgeonHandoff.created_at.desc()).offset(offset).limit(limit).all()
    return {
        "handoffs": [sturgeon_mod.handoff_dict(h) for h in rows],
        "total": total,
        "forwarding_enabled": sturgeon_mod.is_forwarding_enabled(),
    }


@router.get("/sturgeon/handoffs/{handoff_id}", dependencies=[Depends(require_api_key)])
def get_handoff(handoff_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    h = db.query(EchoSturgeonHandoff).filter(EchoSturgeonHandoff.id == handoff_id).first()
    if h is None:
        raise HTTPException(status_code=404, detail=f"Handoff {handoff_id} not found")
    return sturgeon_mod.handoff_dict(h)


# ─── Analytics events ─────────────────────────────────────────────────────────


@router.get("/analytics/events", dependencies=[Depends(require_api_key)])
def list_events(
    event_type: str | None = Query(None),
    workflow_id: str | None = Query(None),
    workflow_run_id: str | None = Query(None),
    tenant_id: str | None = Query(None),
    days_back: int | None = Query(None, ge=1, le=365),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    since = events_mod.window_since(days_back) if days_back else None
    rows = events_mod.query_events(
        db, event_type=event_type, workflow_id=workflow_id,
        workflow_run_id=workflow_run_id, tenant_id=tenant_id,
        since=since, limit=limit, offset=offset,
    )
    return {
        "events": [events_mod.event_dict(e) for e in rows],
        "count": len(rows),
        "counts_in_window": events_mod.event_counts(db, tenant_id=tenant_id, since=since),
    }


# ─── Workflow registry ────────────────────────────────────────────────────────


@router.get("/workflows/registry", dependencies=[Depends(require_api_key)])
def workflow_registry(
    product_area: str | None = Query(None),
) -> dict[str, Any]:
    rows = all_metadata()
    if product_area:
        rows = [r for r in rows if r["product_area"] == product_area]
    return {"workflows": rows, "count": len(rows)}


# ─── Scheduler (Phase 2 — OFF by default) ─────────────────────────────────────


@router.get("/scheduler", dependencies=[Depends(require_api_key)])
def scheduler_status(db: Session = Depends(get_db)) -> dict[str, Any]:
    from echo import scheduling

    scheduling.sync_default_schedules(db)  # ensure defaults exist (disabled)
    return scheduling.scheduler_status(db)


@router.post("/scheduler/tick", dependencies=[Depends(require_api_key)])
def scheduler_tick(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Fire due schedules now — no-op unless ECHO_SCHEDULER_ENABLED=true."""
    from echo import scheduling

    return scheduling.run_due(db)


# ─── Approval-first publishing (Phase 2 — dry-run by default) ─────────────────


class PublishRequest(BaseModel):
    connector: str = "noop"
    actor: str = "operator"
    dry_run: bool | None = None
    tenant_id: str | None = None


@router.get("/connectors", dependencies=[Depends(require_api_key)])
def list_connectors() -> dict[str, Any]:
    return {"connectors": connectors_mod.available_connectors()}


@router.post("/approvals/{approval_id}/publish", dependencies=[Depends(require_api_key)])
def publish_draft(
    approval_id: str, body: PublishRequest, db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Publish an approved draft through a connector (dry-run unless live gate on)."""
    try:
        return publishing_mod.publish_approved(
            db, approval_id, connector=body.connector, actor=body.actor,
            dry_run=body.dry_run, tenant_id=body.tenant_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# ─── Conversion tracking (Phase 2) ────────────────────────────────────────────


class CtaClickRequest(BaseModel):
    campaign: str
    url: str | None = None
    client_id: str | None = None
    source: str | None = None
    medium: str | None = None
    content: str | None = None
    tenant_id: str | None = None


@router.post("/track/cta-click", dependencies=[Depends(require_api_key)])
def track_cta_click(body: CtaClickRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    return conversion_mod.track_cta_click(
        db, campaign=body.campaign, url=body.url, client_id=body.client_id,
        source=body.source, medium=body.medium, content=body.content,
        tenant_id=body.tenant_id or DEFAULT_TENANT_ID,
    )


# ─── Disaster provider status (Phase 2 — NRS/SEMA) ────────────────────────────


@router.get("/disaster/status", dependencies=[Depends(require_api_key)])
def disaster_status() -> dict[str, Any]:
    from echo.integrations import disaster

    return {"providers": disaster.provider_status()}
