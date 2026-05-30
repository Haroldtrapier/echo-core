"""Echo Core background scheduler — processes pending workflow runs."""
from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Any

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


def tick() -> TickReport:
    """Run one scheduler tick — pick up pending workflow runs and execute them."""
    report = TickReport(started_at=datetime.now(timezone.utc))
    with db_session() as db:
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
    return report
