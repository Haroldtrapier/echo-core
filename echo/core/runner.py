"""Workflow runner — executes a workflow, retries on failure, persists the run.

The runner owns the run lifecycle:

    queued → running → (succeeded | completed) on success
                     → retrying → running (up to max_retries)
                     → failed once retries are exhausted

It also emits the analytics spine of the Echo loop:
``workflow_started`` before execution and ``workflow_completed`` /
``workflow_failed`` after. Analytics writes are best-effort and never mask a
workflow's own result.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from echo.core.logger import get_logger
from echo.core.registry import get_workflow
from echo.core.workflow import WorkflowResult
from echo.db import WorkflowRun
from echo.modules import events

log = get_logger("echo.core.runner")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def run_workflow(
    db: Session,
    slug: str,
    payload: dict[str, Any],
    triggered_by: str = "api",
    *,
    max_retries: int | None = None,
    tenant_id: str | None = None,
    user_id: str | None = None,
) -> tuple[WorkflowRun, WorkflowResult]:
    """Look up a workflow, run it (with retries), persist the result, return both.

    ``max_retries`` defaults to the workflow class's own ``max_retries`` attr if
    set, else ``payload['max_retries']``, else 0 (no retry). Retries run inline —
    deterministic and synchronous — so the caller gets the final outcome.
    """
    cls = get_workflow(slug)
    if cls is None:
        raise ValueError(f"Unknown workflow slug: {slug!r}")

    instance = cls()

    validation_errors = instance.validate(payload)
    if validation_errors:
        raise ValueError("; ".join(validation_errors))

    if max_retries is None:
        max_retries = int(
            getattr(cls, "max_retries", 0) or payload.get("max_retries", 0) or 0
        )

    run = WorkflowRun(
        workflow_slug=slug,
        status="running",
        payload=payload,
        triggered_by=triggered_by,
        tenant_id=tenant_id,
        user_id=user_id,
        max_retries=max_retries,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    events.record_event(
        db,
        events.EVENT_WORKFLOW_STARTED,
        workflow_id=slug,
        workflow_run_id=run.id,
        user_id=user_id,
        tenant_id=tenant_id,
        metadata={"triggered_by": triggered_by},
    )

    # Expose run context to workflows that want to link drafts/handoffs/events
    # back to this run, without changing the run() signature.
    exec_payload = {**payload, "_run_id": run.id, "_tenant_id": tenant_id, "_user_id": user_id}

    attempt = 0
    last_exc: Exception | None = None
    result: WorkflowResult | None = None
    while attempt <= max_retries:
        try:
            result = instance.run(db, exec_payload)
            last_exc = None
            break
        except Exception as exc:  # noqa: BLE001 — a failed workflow must not crash the API
            last_exc = exc
            log.exception("Workflow %s run=%s attempt=%d failed: %s", slug, run.id, attempt, exc)
            attempt += 1
            run.retry_count = attempt
            if attempt <= max_retries:
                run.status = "retrying"
                run.updated_at = _utcnow()
                db.commit()

    now = _utcnow()
    if last_exc is not None:
        run.status = "failed"
        run.error = str(last_exc)
        run.updated_at = now
        run.completed_at = now
        db.commit()
        events.record_event(
            db, events.EVENT_WORKFLOW_FAILED, workflow_id=slug, workflow_run_id=run.id,
            user_id=user_id, tenant_id=tenant_id,
            metadata={"error": str(last_exc), "retry_count": run.retry_count},
        )
        return run, WorkflowResult(success=False, error=str(last_exc))

    assert result is not None
    run.status = "succeeded" if result.success else "failed"
    run.result = result.data
    run.error = result.error
    run.updated_at = now
    run.completed_at = now
    db.commit()
    db.refresh(run)

    events.record_event(
        db,
        events.EVENT_WORKFLOW_COMPLETED if result.success else events.EVENT_WORKFLOW_FAILED,
        workflow_id=slug,
        workflow_run_id=run.id,
        user_id=user_id,
        tenant_id=tenant_id,
        metadata={"success": result.success, "message": result.message,
                  "retry_count": run.retry_count},
    )
    log.info("Workflow %s run=%s finished status=%s", slug, run.id, run.status)
    return run, result
