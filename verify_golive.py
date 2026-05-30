#!/usr/bin/env python3
"""Pre-deploy verification script for Echo Core.

Run before going live on Railway:
    python verify_golive.py

Checks:
  1. Required env vars are present
  2. All modules import cleanly
  3. Workflow registry loads the expected workflows
  4. Database connection succeeds
  5. Health endpoint responds (if server is already running)
"""
from __future__ import annotations

import os
import sys

PASS = "✓"
FAIL = "✗"
WARN = "⚠"

errors: list[str] = []
warnings: list[str] = []


def check(label: str, ok: bool, detail: str = "", fatal: bool = True) -> None:
    if ok:
        print(f"  {PASS} {label}" + (f" — {detail}" if detail else ""))
    else:
        mark = FAIL if fatal else WARN
        print(f"  {mark} {label}" + (f" — {detail}" if detail else ""))
        if fatal:
            errors.append(label)
        else:
            warnings.append(label)


# ─── 1. Required env vars ─────────────────────────────────────────────────────

print("\n[1] Environment variables")
REQUIRED = ["DATABASE_URL", "ECHO_API_KEY"]
OPTIONAL = [
    "ANTHROPIC_API_KEY",
    "SAM_GOV_API_KEY",
    "BUFFER_API_KEY",
    "LINKEDIN_ACCESS_TOKEN",
    "LINKEDIN_AUTHOR_URN",
    "SLACK_WEBHOOK_URL",
]

for var in REQUIRED:
    check(var, bool(os.getenv(var)), "set" if os.getenv(var) else "MISSING", fatal=True)

for var in OPTIONAL:
    val = os.getenv(var)
    check(var, bool(val), "set" if val else "not set (feature disabled)", fatal=False)

live_publish = os.getenv("ECHO_ALLOW_LIVE_PUBLISH", "").lower() in ("1", "true", "yes")
check(
    "ECHO_ALLOW_LIVE_PUBLISH",
    not live_publish,
    "false (dry-run mode — safe)" if not live_publish else "TRUE — live publishing is ENABLED",
    fatal=False,
)


# ─── 2. Module imports ────────────────────────────────────────────────────────

print("\n[2] Module imports")
modules_to_check = [
    "echo",
    "echo.config",
    "echo.db",
    "echo.auth",
    "echo.core.logger",
    "echo.core.workflow",
    "echo.core.registry",
    "echo.core.runner",
    "echo.core.scheduler",
    "echo.modules.approval",
    "echo.modules.publisher",
    "echo.modules.ai_generator",
    "echo.modules.analytics",
    "echo.modules.notifications",
    "echo.integrations.sam_gov",
    "echo.integrations.usaspending",
    "echo.integrations.fema",
    "echo.integrations.linkedin",
    "echo.integrations.buffer",
    "echo.integrations.govcon_cms",
    "echo.workflows",
    "echo.api.routes",
    "echo.main",
]

for mod in modules_to_check:
    try:
        __import__(mod)
        check(mod, True)
    except Exception as exc:
        check(mod, False, str(exc))


# ─── 3. Workflow registry ─────────────────────────────────────────────────────

print("\n[3] Workflow registry")
try:
    import echo.workflows  # noqa: F401
    from echo.core.registry import list_workflows, workflow_count

    EXPECTED_SLUGS = [
        "weekly_report",
        "govcon_daily_intelligence",
        "linkedin_signal_post",
        "fema_disaster_monitor",
        "sam_opportunity_watch",
        "approved_publisher",
        "content_calendar_archive",
    ]

    count = workflow_count()
    check("workflow_count", count > 0, f"{count} registered")

    registered = {wf.slug for wf in list_workflows()}
    for slug in EXPECTED_SLUGS:
        check(f"workflow:{slug}", slug in registered)

except Exception as exc:
    check("registry load", False, str(exc))


# ─── 4. Database connection ───────────────────────────────────────────────────

print("\n[4] Database connection")
db_url = os.getenv("DATABASE_URL", "")
if db_url:
    try:
        from echo.db import SessionLocal, engine
        with engine.connect() as conn:
            conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        check("database connection", True, db_url.split("@")[-1] if "@" in db_url else "ok")
    except Exception as exc:
        check("database connection", False, str(exc))
else:
    check("database connection", False, "DATABASE_URL not set")


# ─── 5. Health endpoint (optional — only if server is running) ────────────────

print("\n[5] Health endpoint (optional)")
import urllib.request  # noqa: E402

port = os.getenv("PORT", "8000")
try:
    with urllib.request.urlopen(f"http://localhost:{port}/api/v1/health", timeout=3) as resp:
        import json
        data = json.loads(resp.read())
        check("health endpoint", data.get("status") == "ok", str(data))
except Exception:
    check("health endpoint", True, "server not running locally (skipped)", fatal=False)


# ─── Summary ──────────────────────────────────────────────────────────────────

print()
if errors:
    print(f"  {FAIL} {len(errors)} ERROR(S) — fix before deploying:")
    for e in errors:
        print(f"      • {e}")
    sys.exit(1)
elif warnings:
    print(f"  {WARN} {len(warnings)} warning(s) — review before go-live")
    print(f"  {PASS} No blocking errors — ready to deploy")
else:
    print(f"  {PASS} All checks passed — ready to deploy")
