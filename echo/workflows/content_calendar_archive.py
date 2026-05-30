"""Content calendar archive workflow — mark old published content as archived."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_

from echo.core.registry import register
from echo.core.workflow import BaseWorkflow, WorkflowResult
from echo.db import ContentItem


@register
class ContentCalendarArchiveWorkflow(BaseWorkflow):
    slug = "content_calendar_archive"
    name = "Content Calendar Archive"
    description = (
        "Finds published content items older than the configured retention window "
        "and marks them as 'archived' in the database."
    )

    def run(self, db: Any, payload: dict[str, Any]) -> WorkflowResult:
        retention_days = payload.get("retention_days", 90)
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        dry_run = payload.get("dry_run", True)

        items = (
            db.query(ContentItem)
            .filter(
                and_(
                    ContentItem.published == True,  # noqa: E712
                    ContentItem.status == "published",
                    ContentItem.created_at < cutoff,
                )
            )
            .all()
        )

        if not items:
            return WorkflowResult(
                success=True,
                data={"items_found": 0, "dry_run": dry_run},
                message=f"No content items older than {retention_days} days to archive",
            )

        archived_ids = [str(item.id) for item in items]

        if not dry_run:
            for item in items:
                item.status = "archived"
                item.updated_at = datetime.now(timezone.utc)
            db.commit()

        return WorkflowResult(
            success=True,
            data={
                "items_found": len(items),
                "archived_ids": archived_ids,
                "dry_run": dry_run,
                "retention_days": retention_days,
            },
            message=(
                f"{'Would archive' if dry_run else 'Archived'} "
                f"{len(items)} content item(s) older than {retention_days} days"
            ),
        )
