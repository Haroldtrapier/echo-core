"""Analytics event recording — the append-only Echo event stream.

Every meaningful state transition in the Echo loop writes one immutable row to
``echo_analytics_events`` via :func:`record_event`. This is deliberately separate
from the aggregate ``analytics.get_summary`` (which counts other tables): the
event stream is the source of truth for "what happened, when, and by whom" and
powers the Weekly Performance Tracker and any downstream dashboards.

Recording is best-effort: a failure to write an analytics event must never break
the workflow that triggered it, so all writes are wrapped and swallowed with a log.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from echo.core.logger import get_logger
from echo.db import EchoAnalyticsEvent

log = get_logger("echo.modules.events")

# Canonical event types tracked by the Echo loop.
EVENT_WORKFLOW_STARTED = "workflow_started"
EVENT_WORKFLOW_COMPLETED = "workflow_completed"
EVENT_WORKFLOW_FAILED = "workflow_failed"
EVENT_DRAFT_CREATED = "draft_created"
EVENT_DRAFT_APPROVED = "draft_approved"
EVENT_DRAFT_REJECTED = "draft_rejected"
EVENT_DRAFT_PUBLISHED_OR_READY = "draft_published_or_marked_ready"
EVENT_STURGEON_HANDOFF_CREATED = "sturgeon_handoff_created"
EVENT_LEAD_NURTURE_CREATED = "lead_nurture_created"

KNOWN_EVENT_TYPES = frozenset(
    {
        EVENT_WORKFLOW_STARTED,
        EVENT_WORKFLOW_COMPLETED,
        EVENT_WORKFLOW_FAILED,
        EVENT_DRAFT_CREATED,
        EVENT_DRAFT_APPROVED,
        EVENT_DRAFT_REJECTED,
        EVENT_DRAFT_PUBLISHED_OR_READY,
        EVENT_STURGEON_HANDOFF_CREATED,
        EVENT_LEAD_NURTURE_CREATED,
    }
)


def record_event(
    db: Session,
    event_type: str,
    *,
    workflow_id: str | None = None,
    workflow_run_id: str | None = None,
    user_id: str | None = None,
    tenant_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    commit: bool = True,
) -> EchoAnalyticsEvent | None:
    """Append one analytics event. Best-effort — never raises to the caller.

    ``commit=False`` lets a caller batch the event into an existing transaction
    (e.g. the runner records completion in the same commit as the run update).
    """
    try:
        event = EchoAnalyticsEvent(
            event_type=event_type,
            workflow_id=workflow_id,
            workflow_run_id=workflow_run_id,
            user_id=user_id,
            tenant_id=tenant_id,
            event_metadata=metadata or {},
        )
        db.add(event)
        if commit:
            db.commit()
            db.refresh(event)
        else:
            db.flush()
        return event
    except Exception as exc:  # noqa: BLE001 — analytics must never break the loop
        log.warning("Failed to record analytics event %s: %s", event_type, exc)
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return None


def query_events(
    db: Session,
    *,
    event_type: str | None = None,
    workflow_id: str | None = None,
    workflow_run_id: str | None = None,
    tenant_id: str | None = None,
    since: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[EchoAnalyticsEvent]:
    q = db.query(EchoAnalyticsEvent)
    if event_type:
        q = q.filter(EchoAnalyticsEvent.event_type == event_type)
    if workflow_id:
        q = q.filter(EchoAnalyticsEvent.workflow_id == workflow_id)
    if workflow_run_id:
        q = q.filter(EchoAnalyticsEvent.workflow_run_id == workflow_run_id)
    if tenant_id:
        q = q.filter(EchoAnalyticsEvent.tenant_id == tenant_id)
    if since:
        q = q.filter(EchoAnalyticsEvent.created_at >= since)
    return (
        q.order_by(EchoAnalyticsEvent.created_at.desc()).offset(offset).limit(limit).all()
    )


def event_counts(
    db: Session,
    *,
    tenant_id: str | None = None,
    since: datetime | None = None,
) -> dict[str, int]:
    """Return ``{event_type: count}`` over an optional window/tenant.

    Used by the Weekly Performance Tracker to summarise the period.
    """
    q = db.query(EchoAnalyticsEvent.event_type, func.count(EchoAnalyticsEvent.id))
    if tenant_id:
        q = q.filter(EchoAnalyticsEvent.tenant_id == tenant_id)
    if since:
        q = q.filter(EchoAnalyticsEvent.created_at >= since)
    rows = q.group_by(EchoAnalyticsEvent.event_type).all()
    return {etype: int(n) for etype, n in rows}


def window_since(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


def event_dict(e: EchoAnalyticsEvent) -> dict[str, Any]:
    return {
        "id": e.id,
        "event_type": e.event_type,
        "workflow_id": e.workflow_id,
        "workflow_run_id": e.workflow_run_id,
        "user_id": e.user_id,
        "tenant_id": e.tenant_id,
        "metadata": e.event_metadata,
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }
