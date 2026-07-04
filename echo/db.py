"""Echo Core database layer — SQLAlchemy engine, session, Base, and ORM models."""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Generator

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from echo.config import DATABASE_URL

# ── Engine ────────────────────────────────────────────────────────────────────

_connect_args: dict = {}
if DATABASE_URL.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}

engine = create_engine(
    DATABASE_URL,
    connect_args=_connect_args,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ── Base ──────────────────────────────────────────────────────────────────────


class Base(DeclarativeBase):
    pass


# ── Helpers ───────────────────────────────────────────────────────────────────


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return uuid.uuid4().hex[:16]


def _new_uuid() -> str:
    return uuid.uuid4().hex


# ── ORM Models ────────────────────────────────────────────────────────────────

# ─── Workflow Registry ────────────────────────────────────────────────────────


class WorkflowRun(Base):
    """Tracks a single workflow execution."""

    __tablename__ = "workflow_runs"
    __table_args__ = (Index("ix_workflow_runs_status", "status"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    workflow_slug: Mapped[str] = mapped_column(String(128), nullable=False)
    #: queued | running | approval_required | approved | rejected |
    #: succeeded | completed | failed | retrying
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    tenant_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payload: Mapped[Any] = mapped_column(JSON, nullable=True)
    result: Mapped[Any] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=0)
    triggered_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


# ─── Approvals ────────────────────────────────────────────────────────────────


class Approval(Base):
    """Human-in-the-loop approval record."""

    __tablename__ = "approvals"
    __table_args__ = (Index("ix_approvals_status", "status"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    run_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    requested_by: Mapped[str] = mapped_column(String(255), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    #: Kind of AI-generated draft this approval gates — one of
    #: brief | linkedin_post | email | alert | handoff (free-form; nullable for
    #: legacy publish-gate approvals that carry no draft body).
    draft_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    #: The reviewable draft body (the content a human approves before it ships).
    draft_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: post_id of the linked ContentItem, when the draft is also a content row.
    content_post_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decision_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resume_payload: Mapped[Any] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


# ─── Content Items ────────────────────────────────────────────────────────────


class ContentItem(Base):
    """Read model for GET /content — cockpit content feed."""

    __tablename__ = "content_items"
    __table_args__ = (
        Index("ix_content_items_brand", "brand"),
        Index("ix_content_items_workflow", "workflow"),
        Index("ix_content_items_status", "status"),
        Index("ix_content_items_post_id", "post_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    brand: Mapped[str | None] = mapped_column(String(128), nullable=True)
    workflow: Mapped[str | None] = mapped_column(String(128), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    topic: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    cta_text: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cta_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    utm_source: Mapped[str | None] = mapped_column(String(128), nullable=True)
    utm_medium: Mapped[str | None] = mapped_column(String(128), nullable=True)
    utm_campaign: Mapped[str | None] = mapped_column(String(255), nullable=True)
    utm_content: Mapped[str | None] = mapped_column(String(255), nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    published_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


# ─── Publishing Jobs ──────────────────────────────────────────────────────────


class PublishingJob(Base):
    """Read model for GET /publishing-jobs — platform publishing queue."""

    __tablename__ = "publishing_jobs"
    __table_args__ = (
        Index("ix_publishing_jobs_post_id", "post_id"),
        Index("ix_publishing_jobs_platform", "platform"),
        Index("ix_publishing_jobs_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(64), nullable=False, default=_new_id)
    post_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    platform: Mapped[str | None] = mapped_column(String(64), nullable=True)
    channel_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    scheduling_mode: Mapped[str] = mapped_column(String(32), default="immediate")
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    external_post_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    published_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


# ─── Automation Logs ──────────────────────────────────────────────────────────


class AutomationLog(Base):
    """Append-only structured log for GET /logs."""

    __tablename__ = "automation_logs"
    __table_args__ = (
        Index("ix_automation_logs_brand", "brand"),
        Index("ix_automation_logs_workflow", "workflow"),
        Index("ix_automation_logs_level", "level"),
        Index("ix_automation_logs_run_id", "run_id"),
        Index("ix_automation_logs_post_id", "post_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    log_id: Mapped[str] = mapped_column(String(64), nullable=False, default=_new_id)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    brand: Mapped[str | None] = mapped_column(String(128), nullable=True)
    workflow: Mapped[str | None] = mapped_column(String(128), nullable=True)
    step: Mapped[str | None] = mapped_column(String(255), nullable=True)
    level: Mapped[str] = mapped_column(String(16), default="info")
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    post_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    raw_payload: Mapped[Any] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


# ─── Integration Health ───────────────────────────────────────────────────────


class IntegrationHealth(Base):
    """Read model for GET /integration-health."""

    __tablename__ = "integration_health"
    __table_args__ = (
        Index("ix_integration_health_integration", "integration"),
        Index("ix_integration_health_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    integration: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="unknown")
    last_checked: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_success: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_failure: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    credential_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


# ─── Echo Jobs ────────────────────────────────────────────────────────────────


class EchoJob(Base):
    """Control-panel job: a piece of content queued for Echo automation."""

    __tablename__ = "echo_jobs"
    __table_args__ = (
        Index("ix_echo_jobs_tenant", "tenant_id"),
        Index("ix_echo_jobs_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    tenant_id: Mapped[str] = mapped_column(String(255), nullable=False, default="imani-internal")
    created_by: Mapped[str] = mapped_column(String(255), nullable=False, default="apex-operator")
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    channel: Mapped[str] = mapped_column(String(64), nullable=False, default="linkedin")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str | None] = mapped_column(String(512), nullable=True)
    job_metadata: Mapped[Any] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    approval_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    dry_run_result: Mapped[Any] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class EchoJobSchedule(Base):
    """A future-dated trigger that runs an EchoJob dry-run when due."""

    __tablename__ = "echo_job_schedules"
    __table_args__ = (Index("ix_echo_job_schedules_job", "echo_job_id"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    tenant_id: Mapped[str] = mapped_column(String(255), nullable=False, default="imani-internal")
    echo_job_id: Mapped[str] = mapped_column(String(32), nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False, default="apex-operator")
    scheduled_for: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    run_count: Mapped[int] = mapped_column(Integer, default=0)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_result: Mapped[Any] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class EchoExecutionAudit(Base):
    """Immutable audit log for every execute / dry-run attempt on an EchoJob."""

    __tablename__ = "echo_execution_audits"
    __table_args__ = (Index("ix_echo_execution_audits_job", "echo_job_id"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    tenant_id: Mapped[str] = mapped_column(String(255), nullable=False, default="imani-internal")
    echo_job_id: Mapped[str] = mapped_column(String(32), nullable=False)
    approval_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    workflow_run_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    attempted_by: Mapped[str] = mapped_column(String(255), nullable=False, default="apex-operator")
    action: Mapped[str] = mapped_column(String(64), nullable=False, default="execute")
    result: Mapped[str] = mapped_column(String(64), nullable=False)
    approval_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    live_publish_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_metadata: Mapped[Any] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


# ─── Echo Workflow Registry (DB mirror) ───────────────────────────────────────


class EchoWorkflow(Base):
    """Durable mirror of the in-code workflow registry.

    The authoritative registry is the Python decorator registry (echo.core.registry);
    this table is synced from it on startup so dashboards, entitlement checks, and
    schedulers can read workflow metadata (tier, product area, approval policy)
    without importing Python. ``workflow_id`` == the code ``slug``.
    """

    __tablename__ = "echo_workflows"
    __table_args__ = (
        Index("ix_echo_workflows_product_area", "product_area"),
        Index("ix_echo_workflows_enabled", "enabled"),
    )

    workflow_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    workflow_name: Mapped[str] = mapped_column(String(255), nullable=False)
    product_area: Mapped[str] = mapped_column(String(64), nullable=False, default="echo_core")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    trigger_type: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    input_schema: Mapped[Any] = mapped_column(JSON, nullable=True)
    output_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approval_required: Mapped[bool] = mapped_column(Boolean, default=False)
    connector_targets: Mapped[Any] = mapped_column(JSON, nullable=True)
    required_tier: Mapped[str] = mapped_column(String(32), nullable=False, default="free")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


# ─── Echo Analytics Events ────────────────────────────────────────────────────


class EchoAnalyticsEvent(Base):
    """Append-only analytics event stream for the Echo loop.

    Every meaningful state transition (workflow_started/completed/failed,
    draft_created/approved/rejected, draft_published_or_marked_ready,
    sturgeon_handoff_created, lead_nurture_created) writes one immutable row here.
    """

    __tablename__ = "echo_analytics_events"
    __table_args__ = (
        Index("ix_echo_analytics_events_type", "event_type"),
        Index("ix_echo_analytics_events_workflow", "workflow_id"),
        Index("ix_echo_analytics_events_run", "workflow_run_id"),
        Index("ix_echo_analytics_events_tenant", "tenant_id"),
        Index("ix_echo_analytics_events_created", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    workflow_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    workflow_run_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tenant_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    event_metadata: Mapped[Any] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


# ─── Echo Sturgeon Handoffs ───────────────────────────────────────────────────


class EchoSturgeonHandoff(Base):
    """A GovCon opportunity handed off from Echo GovCon into Sturgeon AI.

    Minimal, safe handoff record. If ``STURGEON_API_URL`` is configured the
    handoff is also POSTed to Sturgeon and ``forwarded`` is set; otherwise it is
    stored locally as ``pending`` for Sturgeon to pull.
    """

    __tablename__ = "echo_sturgeon_handoffs"
    __table_args__ = (
        Index("ix_echo_sturgeon_handoffs_tenant", "tenant_id"),
        Index("ix_echo_sturgeon_handoffs_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    tenant_id: Mapped[str] = mapped_column(String(255), nullable=False, default="imani-internal")
    workflow_run_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    approval_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False, default="echo_govcon")
    opportunity_title: Mapped[str] = mapped_column(String(512), nullable=False)
    agency: Mapped[str | None] = mapped_column(String(255), nullable=True)
    solicitation_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    due_date: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    requirements: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommended_next_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: pending → stored locally, awaiting Sturgeon pull
    #: forwarded → POSTed to Sturgeon successfully
    #: failed → forward attempted but errored
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    sturgeon_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    forward_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra: Mapped[Any] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


# ─── Echo Schedules (Phase 2 scheduler) ───────────────────────────────────────


class EchoSchedule(Base):
    """A recurring workflow schedule. Interval-based; disabled by default.

    The scheduler only acts on these when ``ECHO_SCHEDULER_ENABLED`` is true AND
    the individual row's ``enabled`` flag is true — two independent off-switches.
    """

    __tablename__ = "echo_schedules"
    __table_args__ = (
        Index("ix_echo_schedules_slug", "workflow_slug"),
        Index("ix_echo_schedules_enabled", "enabled"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    workflow_slug: Mapped[str] = mapped_column(String(128), nullable=False)
    interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=1440)
    payload: Mapped[Any] = mapped_column(JSON, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    tenant_id: Mapped[str] = mapped_column(String(255), nullable=False, default="imani-internal")
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_run_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    run_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


# ── Session helpers ───────────────────────────────────────────────────────────

# Tracks whether create_tables() has succeeded at least once.
# startup() catches exceptions silently; the first DB request retries if needed.
_tables_initialized: bool = False


def ensure_tables() -> None:
    """Create all tables idempotently.  Safe to call multiple times."""
    global _tables_initialized
    if not _tables_initialized:
        Base.metadata.create_all(bind=engine)
        _tables_initialized = True


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a database session.

    Retries table creation on the first request in case the startup handler
    failed (e.g. DB not yet ready when the process started).
    """
    ensure_tables()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def db_session() -> Generator[Session, None, None]:
    """Context manager for non-FastAPI code (worker, scripts)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables() -> None:
    """Create all tables if they don't exist (used by worker on startup)."""
    Base.metadata.create_all(bind=engine)
    global _tables_initialized
    _tables_initialized = True
