"""Echo Core background scheduler — processes pending workflow runs.

Two responsibilities per tick:

1. **Queued runs** — execute any ``workflow_runs`` rows left in ``pending``
   (e.g. enqueued by an external system).
2. **Scheduled cadence** — auto-run workflows whose ``trigger_type == "scheduled"``
   when their cadence is due. A workflow's cadence is ``schedule_interval_seconds``
   (class attr), overridable per deploy with ``ECHO_SCHEDULE_<SLUG>`` (seconds;
   ``0`` or a negative value disables it). "Due" means the workflow has never been
   run by the scheduler, or its last scheduler run was at least one interval ago.

Everything is dry-run/approval-first downstream — the scheduler only *triggers*
runs; it never publishes.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func

from echo.core.logger import get_logger
from echo.core.registry import list_workflows
from echo.core.runner import run_workflow
from echo.db import WorkflowRun, db_session

log = get_logger("echo.core.scheduler")


@dataclass
class TickReport:
    started_at: datetime
    processed: int = 0
    succeeded: list[str] = field(default_factory=list)
    failed: list[dict[str, Any]] = field(default_factory=list)
    #: Slugs auto-triggered this tick because their scheduled cadence was due.
    scheduled: list[str] = field(default_factory=list)

    @property
    def failed_count(self) -> int:
        return len(self.failed)


def resolve_schedule_seconds(cls: Any) -> int | None:
    """Effective cadence (seconds) for a workflow, or ``None`` if not scheduled.

    ``ECHO_SCHEDULE_<SLUG>`` (uppercased slug) overrides the class attribute.
    ``0`` / negative / unparseable disables the cadence.
    """
    slug = getattr(cls, "slug", "") or ""
    env = os.getenv(f"ECHO_SCHEDULE_{slug.upper()}")
    raw: Any = env if env is not None else getattr(cls, "schedule_interval_seconds", None)
    if raw is None or raw == "":
        return None
    try:
        seconds = int(raw)
    except (TypeError, ValueError):
        log.warning("Ignoring invalid schedule for %s: %r", slug, raw)
        return None
    return seconds if seconds > 0 else None


def _last_scheduler_run_at(db: Any, slug: str) -> datetime | None:
    """When the scheduler last triggered ``slug`` (max created_at), or None."""
    ts = (
        db.query(func.max(WorkflowRun.created_at))
        .filter(
            WorkflowRun.workflow_slug == slug,
            WorkflowRun.triggered_by == "scheduler",
        )
        .scalar()
    )
    if ts is not None and ts.tzinfo is None:
        # SQLite/naive columns — treat stored times as UTC.
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def _due_scheduled_workflows(db: Any, now: datetime) -> list[str]:
    """Slugs whose scheduled cadence is due to run now."""
    due: list[str] = []
    for cls in list_workflows():
        if getattr(cls, "trigger_type", "manual") != "scheduled":
            continue
        if not getattr(cls, "enabled", True):
            continue
        interval = resolve_schedule_seconds(cls)
        if interval is None:
            continue
        last = _last_scheduler_run_at(db, cls.slug)
        if last is None or (now - last).total_seconds() >= interval:
            due.append(cls.slug)
    return due


def _tick(db: Any) -> TickReport:
    report = TickReport(started_at=datetime.now(timezone.utc))

    # 1) Execute explicitly-queued pending runs.
    pending = (
        db.query(WorkflowRun)
        .filter(WorkflowRun.status == "pending")
        .order_by(WorkflowRun.created_at)
        .limit(50)
        .all()
    )
    report.processed = len(pending)
    for run in pending:
        try:
            _, result = run_workflow(
                db, run.workflow_slug, run.payload or {}, triggered_by="scheduler"
            )
            if result.success:
                report.succeeded.append(run.id)
            else:
                report.failed.append({"run_id": run.id, "error": result.error})
        except Exception as exc:  # noqa: BLE001
            log.exception("Scheduler failed run=%s: %s", run.id, exc)
            report.failed.append({"run_id": run.id, "error": str(exc)})

    # 2) Auto-run scheduled workflows whose cadence is due.
    for slug in _due_scheduled_workflows(db, report.started_at):
        try:
            run, result = run_workflow(db, slug, {}, triggered_by="scheduler")
            report.scheduled.append(slug)
            if result.success:
                report.succeeded.append(run.id)
            else:
                report.failed.append({"run_id": run.id, "error": result.error})
        except Exception as exc:  # noqa: BLE001
            log.exception("Scheduled cadence run failed slug=%s: %s", slug, exc)
            report.failed.append({"slug": slug, "error": str(exc)})

    return report


def tick(db: Any | None = None) -> TickReport:
    """Run one scheduler tick.

    Accepts an optional live session (the worker passes one so a single DB
    connection spans the tick). When omitted, opens and closes its own session.
    """
    if db is not None:
        return _tick(db)
    with db_session() as own:
        return _tick(own)
