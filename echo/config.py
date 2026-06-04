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
# GA4 (Google Analytics 4) — read-only campaign attribution for the Weekly Report.
GA4_PROPERTY_ID: str = os.getenv("GA4_PROPERTY_ID", "")
GA4_ACCESS_TOKEN: str = os.getenv("GA4_ACCESS_TOKEN", "")

# ── Worker ────────────────────────────────────────────────────────────────────
# How often (seconds) the background worker ticks the scheduler
WORKER_TICK_INTERVAL: int = int(os.getenv("WORKER_TICK_INTERVAL", "60"))

# ── CORS ──────────────────────────────────────────────────────────────────────
_raw_cors = os.getenv("CORS_ORIGINS", "*")
CORS_ORIGINS: list[str] = (
    ["*"] if _raw_cors.strip() == "*"
    else [o.strip() for o in _raw_cors.split(",") if o.strip()]
)
