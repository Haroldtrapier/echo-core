"""Base workflow class for Echo Core."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class WorkflowResult:
    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    completed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class BaseWorkflow(ABC):
    """All Echo workflows subclass this."""

    #: Unique slug used in the registry and API (e.g. 'weekly_report')
    slug: str = ""
    #: Human-readable display name
    name: str = ""
    #: One-line description for GET /workflows
    description: str = ""
    #: Whether this workflow can be triggered via webhook
    webhook_enabled: bool = False

    @abstractmethod
    def run(self, payload: dict[str, Any]) -> WorkflowResult:
        """Execute the workflow. Must return a WorkflowResult."""

    def validate(self, payload: dict[str, Any]) -> str | None:
        """Optional payload validation. Return error string or None."""
        return None
