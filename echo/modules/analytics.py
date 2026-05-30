"""Analytics module — summary stats for GET /analytics/summary."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from echo.db import AutomationLog, ContentItem, IntegrationHealth, PublishingJob, WorkflowRun


def get_summary(db: Session) -> dict[str, Any]:
    """Aggregate counts and health stats for the analytics summary endpoint."""
    now = datetime.now(timezone.utc)
    last_24h = now - timedelta(hours=24)
    last_7d = now - timedelta(days=7)

    total_runs = db.query(func.count(WorkflowRun.id)).scalar() or 0
    runs_24h = db.query(func.count(WorkflowRun.id)).filter(WorkflowRun.created_at >= last_24h).scalar() or 0
    runs_succeeded = db.query(func.count(WorkflowRun.id)).filter(WorkflowRun.status == "succeeded").scalar() or 0
    runs_failed = db.query(func.count(WorkflowRun.id)).filter(WorkflowRun.status == "failed").scalar() or 0

    content_total = db.query(func.count(ContentItem.id)).scalar() or 0
    content_published = db.query(func.count(ContentItem.id)).filter(ContentItem.published == True).scalar() or 0  # noqa: E712
    content_pending = db.query(func.count(ContentItem.id)).filter(ContentItem.status == "draft").scalar() or 0

    pub_jobs_total = db.query(func.count(PublishingJob.id)).scalar() or 0
    pub_jobs_success = db.query(func.count(PublishingJob.id)).filter(PublishingJob.status == "published").scalar() or 0
    pub_jobs_failed = db.query(func.count(PublishingJob.id)).filter(PublishingJob.status == "failed").scalar() or 0

    errors_24h = (
        db.query(func.count(AutomationLog.id))
        .filter(AutomationLog.level == "error", AutomationLog.created_at >= last_24h)
        .scalar() or 0
    )

    integrations_healthy = (
        db.query(func.count(IntegrationHealth.id))
        .filter(IntegrationHealth.status == "healthy")
        .scalar() or 0
    )
    integrations_down = (
        db.query(func.count(IntegrationHealth.id))
        .filter(IntegrationHealth.status == "down")
        .scalar() or 0
    )

    return {
        "generated_at": now.isoformat(),
        "workflows": {
            "total_runs": total_runs,
            "runs_last_24h": runs_24h,
            "succeeded": runs_succeeded,
            "failed": runs_failed,
            "success_rate": round(runs_succeeded / total_runs * 100, 1) if total_runs else 0,
        },
        "content": {
            "total": content_total,
            "published": content_published,
            "pending_draft": content_pending,
        },
        "publishing_jobs": {
            "total": pub_jobs_total,
            "succeeded": pub_jobs_success,
            "failed": pub_jobs_failed,
        },
        "logs": {
            "errors_last_24h": errors_24h,
        },
        "integrations": {
            "healthy": integrations_healthy,
            "down": integrations_down,
        },
    }
