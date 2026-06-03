"""Workflow runner — executes a workflow and persists the run record."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from echo.core.logger import get_logger
from echo.core.registry import get_workflow
from echo.core.workflow import WorkflowResult
from echo.db import WorkflowRun

log = get_logger("echo.core.runner")


def run_workflow(
    db: Session,
    slug: str,
    payload: dict[str, Any],
    triggered_by: str = "api",
) -> tuple[WorkflowRun, WorkflowResult]:
    """Look up a workflow, run it, persist the result, return both."""
    cls = get_workflow(slug)
    if cls is None:
        raise ValueError(f"Unknown workflow slug: {slug!r}")

    instance = cls()

    validation_errors = instance.validate(payload)
    if validation_errors:
        raise ValueError("; ".join(validation_errors))

    run = WorkflowRun(
        workflow_slug=slug,
        status="running",
        payload=payload,
        triggered_by=triggered_by,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    try:
        result = instance.run(db, payload)
    except Exception as exc:
        log.exception("Workflow %s run=%s failed: %s", slug, run.id, exc)
        run.status = "failed"
        run.error = str(exc)
        run.updated_at = datetime.now(timezone.utc)
        db.commit()
        return run, WorkflowResult(success=False, error=str(exc))

    run.status = "succeeded" if result.success else "failed"
    run.result = result.data
    run.error = result.error
    run.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(run)
    log.info("Workflow %s run=%s finished status=%s", slug, run.id, run.status)
    return run, result
