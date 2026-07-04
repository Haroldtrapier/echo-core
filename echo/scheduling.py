"""Echo workflow scheduler (Phase 2) — recurring, interval-based, OFF by default.

Two independent off-switches protect production:
  1. ``ECHO_SCHEDULER_ENABLED`` (global env flag) — false by default.
  2. each ``EchoSchedule.enabled`` row flag — false by default.

Nothing auto-runs unless BOTH are true. ``run_due`` is a no-op that reports
``skipped`` when the global flag is off, so the worker can call it every tick
safely even in production.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from echo.config import DEFAULT_TENANT_ID, ECHO_SCHEDULER_ENABLED
from echo.core.logger import get_logger
from echo.db import EchoSchedule

log = get_logger("echo.scheduling")

DAILY = 24 * 60
WEEKLY = 7 * 24 * 60

# Default schedules seeded (disabled) so operators can flip them on per-row.
DEFAULT_SCHEDULES: list[dict[str, Any]] = [
    {
        "name": "Daily GovCon Brief",
        "workflow_slug": "govcon_daily_brief",
        "interval_minutes": DAILY,
        "payload": {"keywords": ["information technology", "cybersecurity", "cloud"]},
    },
    {
        "name": "Weekly Performance Tracker",
        "workflow_slug": "weekly_performance_tracker",
        "interval_minutes": WEEKLY,
        "payload": {},
    },
]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def sync_default_schedules(db: Session) -> int:
    """Idempotently seed the default schedules (disabled). Returns rows ensured."""
    count = 0
    try:
        for spec in DEFAULT_SCHEDULES:
            existing = (
                db.query(EchoSchedule)
                .filter(EchoSchedule.workflow_slug == spec["workflow_slug"])
                .first()
            )
            if existing is None:
                db.add(
                    EchoSchedule(
                        name=spec["name"],
                        workflow_slug=spec["workflow_slug"],
                        interval_minutes=spec["interval_minutes"],
                        payload=spec["payload"],
                        enabled=False,  # never auto-enable
                        tenant_id=DEFAULT_TENANT_ID,
                    )
                )
                count += 1
        db.commit()
    except Exception as exc:  # noqa: BLE001
        log.warning("Schedule seed skipped: %s", exc)
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
    return count


def is_due(schedule: EchoSchedule, now: datetime | None = None) -> bool:
    now = now or _utcnow()
    if not schedule.enabled:
        return False
    if schedule.last_run_at is None:
        return True
    return schedule.last_run_at + timedelta(minutes=schedule.interval_minutes) <= now


def due_schedules(db: Session, now: datetime | None = None) -> list[EchoSchedule]:
    now = now or _utcnow()
    rows = db.query(EchoSchedule).filter(EchoSchedule.enabled == True).all()  # noqa: E712
    return [s for s in rows if is_due(s, now)]


def run_due(db: Session, now: datetime | None = None) -> dict[str, Any]:
    """Run all due schedules — but ONLY if the global flag is enabled.

    Returns a report. When the global flag is off this is a pure no-op with
    ``skipped=True`` — safe to call on every worker tick in production.
    """
    now = now or _utcnow()
    if not ECHO_SCHEDULER_ENABLED:
        return {"skipped": True, "reason": "ECHO_SCHEDULER_ENABLED is false",
                "enabled": False, "ran": []}

    from echo.core.runner import run_workflow

    ran: list[dict[str, Any]] = []
    for s in due_schedules(db, now):
        try:
            run, result = run_workflow(
                db, s.workflow_slug, dict(s.payload or {}),
                triggered_by="scheduler", tenant_id=s.tenant_id,
            )
            s.last_run_at = now
            s.next_run_at = now + timedelta(minutes=s.interval_minutes)
            s.last_run_id = run.id
            s.run_count += 1
            db.commit()
            ran.append({"schedule_id": s.id, "workflow_slug": s.workflow_slug,
                        "run_id": run.id, "status": run.status})
        except Exception as exc:  # noqa: BLE001
            log.exception("Scheduled run failed for %s: %s", s.workflow_slug, exc)
            ran.append({"schedule_id": s.id, "workflow_slug": s.workflow_slug,
                        "error": str(exc)})
    return {"skipped": False, "enabled": True, "ran": ran, "count": len(ran)}


def schedule_dict(s: EchoSchedule) -> dict[str, Any]:
    return {
        "id": s.id,
        "name": s.name,
        "workflow_slug": s.workflow_slug,
        "interval_minutes": s.interval_minutes,
        "enabled": s.enabled,
        "tenant_id": s.tenant_id,
        "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
        "next_run_at": s.next_run_at.isoformat() if s.next_run_at else None,
        "last_run_id": s.last_run_id,
        "run_count": s.run_count,
    }


def scheduler_status(db: Session) -> dict[str, Any]:
    schedules = db.query(EchoSchedule).order_by(EchoSchedule.name).all()
    return {
        "scheduler_enabled": ECHO_SCHEDULER_ENABLED,
        "schedules": [schedule_dict(s) for s in schedules],
        "note": (
            "Scheduler is OFF unless ECHO_SCHEDULER_ENABLED=true AND a schedule's "
            "own enabled flag is true."
        ),
    }
