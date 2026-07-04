"""Echo Core background scheduler — pending runs + recurring schedules."""
from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from echo.core.logger import get_logger
from echo.core.runner import run_workflow
from echo.db import WorkflowRun, db_session

log = get_logger("echo.core.scheduler")


@dataclass
class TickReport:
    started_at: datetime
    processed: int = 0
    succeeded: list[str] = field(default_factory=list)
    failed: list[dict[str, Any]] = field(default_factory=list)
    #: report from the recurring-schedule pass (no-op unless scheduler enabled)
    scheduled: dict[str, Any] | None = None


def tick(db: Session | None = None) -> TickReport:
    """Run one scheduler tick.

    Two responsibilities:
      1. Pick up any queued (``pending``) workflow runs and execute them.
      2. Fire due recurring schedules — but only when ``ECHO_SCHEDULER_ENABLED``
         is true (``scheduling.run_due`` self-gates and no-ops otherwise).

    Accepts an optional session (the worker passes one); opens its own if omitted.
    """
    if db is None:
        with db_session() as _db:
            return tick(_db)

    report = TickReport(started_at=datetime.now(timezone.utc))

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
        except Exception as exc:
            log.exception("Scheduler failed run=%s: %s", run.id, exc)
            report.failed.append({"run_id": run.id, "error": str(exc)})

    # Recurring schedules (no-op unless ECHO_SCHEDULER_ENABLED).
    try:
        from echo.scheduling import run_due
        report.scheduled = run_due(db)
    except Exception as exc:  # noqa: BLE001
        log.warning("Schedule run_due failed: %s", exc)

    return report
