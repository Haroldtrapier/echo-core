"""Echo Core configuration — loaded from environment variables."""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

# ── Core ──────────────────────────────────────────────────────────────────────
APP_NAME: str = os.getenv("APP_NAME", "Echo Core")
ENV: str = os.getenv("ENV", "production")

# ── Database ──────────────────────────────────────────────────────────────────
# Railway injects DATABASE_URL automatically when a Postgres plugin is attached.
DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./echo.db")

# ── Security ──────────────────────────────────────────────────────────────────
# All non-health endpoints require:  x-echo-key: <value>  OR  Authorization: Bearer <value>
ECHO_API_KEY: str = os.getenv("ECHO_API_KEY", "")

# ── AI ────────────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-3-5-haiku-20241022")

# ── Echo feature flags ────────────────────────────────────────────────────────
ECHO_ENABLED: bool = os.getenv("ECHO_ENABLED", "true").lower() == "true"
# Hard kill-switch: dry-run only until explicitly unlocked
ECHO_ALLOW_LIVE_PUBLISH: bool = os.getenv("ECHO_ALLOW_LIVE_PUBLISH", "false").lower() == "true"

# ── Optional integrations ─────────────────────────────────────────────────────
SAM_GOV_API_KEY: str = os.getenv("SAM_GOV_API_KEY", "")
BUFFER_API_KEY: str = os.getenv("BUFFER_API_KEY", "")
# Comma-separated Buffer profile (channel) ids to target; empty = first connected.
BUFFER_PROFILE_IDS: list[str] = [
    p.strip() for p in os.getenv("BUFFER_PROFILE_IDS", "").split(",") if p.strip()
]
LINKEDIN_ACCESS_TOKEN: str = os.getenv("LINKEDIN_ACCESS_TOKEN", "")
LINKEDIN_AUTHOR_URN: str = os.getenv("LINKEDIN_AUTHOR_URN", "")
# Slack incoming-webhook URL for notifications (optional — alerts are skipped if unset).
SLACK_WEBHOOK_URL: str = os.getenv("SLACK_WEBHOOK_URL", "")
# Email (Resend) — sends approved `email` drafts (lead nurture, certification).
# Both required to send; absent → email dispatch stays dry-run.
RESEND_API_KEY: str = os.getenv("RESEND_API_KEY", "")
EMAIL_FROM: str = os.getenv("EMAIL_FROM", "")
# GA4 (Google Analytics 4) — read-only campaign attribution for the Weekly Report.
GA4_PROPERTY_ID: str = os.getenv("GA4_PROPERTY_ID", "")
GA4_ACCESS_TOKEN: str = os.getenv("GA4_ACCESS_TOKEN", "")

# Disaster feeds beyond FEMA (provisioned adapters — safe no-op when unset).
# NRS: National Response System feed. SEMA: State Emergency Management Agency
# feed; SEMA_API_URL may contain a "{state}" placeholder (e.g.
# https://alerts.example.gov/{state}/declarations.json). Both normalize to the
# FEMA declaration shape and fold into pack.safe_disaster_declarations().
NRS_API_URL: str = os.getenv("NRS_API_URL", "")
NRS_API_KEY: str = os.getenv("NRS_API_KEY", "")
SEMA_API_URL: str = os.getenv("SEMA_API_URL", "")
SEMA_API_KEY: str = os.getenv("SEMA_API_KEY", "")

# Image generation (Instagram creative). OpenAI-compatible images API.
IMAGE_API_KEY: str = os.getenv("IMAGE_API_KEY", "")
IMAGE_API_BASE: str = os.getenv("IMAGE_API_BASE", "https://api.openai.com/v1")
IMAGE_MODEL: str = os.getenv("IMAGE_MODEL", "gpt-image-1")
IMAGE_SIZE: str = os.getenv("IMAGE_SIZE", "1024x1024")

# Video generation ("Echo Complete" / TikTok). Point VIDEO_API_URL at a render
# service that accepts {"script","voice"} and returns {"video_url"}.
VIDEO_API_KEY: str = os.getenv("VIDEO_API_KEY", "")
VIDEO_API_URL: str = os.getenv("VIDEO_API_URL", "")
VIDEO_VOICE: str = os.getenv("VIDEO_VOICE", "default")

# Asset storage (Supabase Storage) — hosts generated media (e.g. base64 images)
# at a public URL so Buffer/Instagram can use it.
SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY: str = os.getenv("SUPABASE_SERVICE_KEY", "")
MEDIA_BUCKET: str = os.getenv("MEDIA_BUCKET", "echo-media")

# ── Tenancy ───────────────────────────────────────────────────────────────────
# Default workspace/tenant used when a caller does not supply one. Echo is
# single-tenant-by-default; multi-tenant callers pass tenant_id explicitly.
DEFAULT_TENANT_ID: str = os.getenv("DEFAULT_TENANT_ID", "imani-internal")
# When true, each DB session sets the `app.current_tenant` GUC so the opt-in
# Row-Level Security policies (migration 0006 → SELECT echo_enable_rls()) scope
# reads/writes to the caller's tenant. Off by default: the standard deployment
# connects as the table owner and bypasses RLS, so single-tenant setups are
# unaffected. Turn this on together with echo_enable_rls() for tenant isolation
# on non-owner/least-privilege DB roles. No-op on SQLite (dev/test).
ECHO_RLS_ENABLED: bool = os.getenv("ECHO_RLS_ENABLED", "false").lower() == "true"

# ── Sturgeon handoff ──────────────────────────────────────────────────────────
# When STURGEON_API_URL is set, Echo GovCon forwards handoffs to Sturgeon's
# intake endpoint. When unset, handoffs are stored locally (status=pending) for
# Sturgeon to pull — no network call is made, so local build/test never needs it.
STURGEON_API_URL: str = os.getenv("STURGEON_API_URL", "")
STURGEON_API_KEY: str = os.getenv("STURGEON_API_KEY", "")
# Public URL a human clicks to open the opportunity in Sturgeon (used in CTAs).
STURGEON_APP_URL: str = os.getenv("STURGEON_APP_URL", "https://sturgeon.ai")

# ── Worker / scheduling ───────────────────────────────────────────────────────
# How often (seconds) the background worker ticks the scheduler
WORKER_TICK_INTERVAL: int = int(os.getenv("WORKER_TICK_INTERVAL", "60"))
# Per-workflow cadence override: set ECHO_SCHEDULE_<SLUG> (uppercased slug) to a
# number of seconds to change how often a scheduled workflow auto-runs, or to 0
# to disable it. Defaults come from each workflow's schedule_interval_seconds.
# Read dynamically in echo.core.scheduler.resolve_schedule_seconds.

# ── CORS ──────────────────────────────────────────────────────────────────────
_raw_cors = os.getenv("CORS_ORIGINS", "*")
CORS_ORIGINS: list[str] = (
    ["*"] if _raw_cors.strip() == "*"
    else [o.strip() for o in _raw_cors.split(",") if o.strip()]
)
