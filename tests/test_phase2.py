"""Phase 2 scaffolding — safety-guard tests.

Everything production-impacting is off by default; these tests prove the guards:
scheduler disabled, live publishing blocked, approval required before publish,
GA4 no-op, NRS/SEMA mock/disabled behavior, and conversion tracking.
"""
from __future__ import annotations

import pytest


# ─── Scheduler: OFF by default ────────────────────────────────────────────────

def test_scheduler_disabled_by_default(client, auth):
    r = client.get("/api/v1/govcon/scheduler", headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["scheduler_enabled"] is False
    # default schedules seeded but disabled
    slugs = {s["workflow_slug"]: s for s in body["schedules"]}
    assert "govcon_daily_brief" in slugs and "weekly_performance_tracker" in slugs
    assert all(s["enabled"] is False for s in body["schedules"])


def test_scheduler_tick_is_noop_when_disabled(client, auth):
    r = client.post("/api/v1/govcon/scheduler/tick", headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["skipped"] is True
    assert body["enabled"] is False
    assert body["ran"] == []


def test_run_due_creates_no_runs_when_disabled():
    """Even with an enabled schedule row, the global flag off ⇒ nothing runs."""
    from datetime import datetime, timezone

    from echo import scheduling
    from echo.db import EchoSchedule, WorkflowRun, db_session

    with db_session() as db:
        before = db.query(WorkflowRun).count()
        db.add(EchoSchedule(name="x", workflow_slug="govcon_daily_brief",
                            interval_minutes=1, enabled=True))
        db.commit()
        report = scheduling.run_due(db, now=datetime.now(timezone.utc))
        after = db.query(WorkflowRun).count()
    assert report["skipped"] is True
    assert after == before  # no runs enqueued/executed while global flag is off


# ─── Live publishing: blocked by default ──────────────────────────────────────

def _make_approved_draft(client, auth):
    gen = client.post("/api/v1/workflows/govcon_daily_brief/run", headers=auth,
                      json={"payload": {}}).json()
    aid = gen["result"]["approval_id"]
    client.post(f"/api/v1/govcon/approvals/{aid}/approve", headers=auth,
                json={"reviewed_by": "tester"})
    return aid


def test_publish_requires_approval_first(client, auth):
    """Publishing a still-pending draft is rejected (403)."""
    gen = client.post("/api/v1/workflows/govcon_daily_brief/run", headers=auth,
                      json={"payload": {}}).json()
    aid = gen["result"]["approval_id"]  # pending, not approved
    r = client.post(f"/api/v1/govcon/approvals/{aid}/publish", headers=auth,
                    json={"connector": "noop"})
    assert r.status_code == 403
    assert "approved" in r.text.lower()


def test_publish_is_dry_run_by_default(client, auth):
    """Approved draft publishes dry-run (never live) while ECHO_ALLOW_LIVE_PUBLISH off."""
    aid = _make_approved_draft(client, auth)
    r = client.post(f"/api/v1/govcon/approvals/{aid}/publish", headers=auth,
                    json={"connector": "noop"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] is True
    assert body["went_live"] is False
    assert body["live_publish_enabled"] is False


def test_publish_cannot_force_live_when_gate_off(client, auth):
    """Even asking for dry_run=false cannot go live when the kill-switch is off."""
    aid = _make_approved_draft(client, auth)
    r = client.post(f"/api/v1/govcon/approvals/{aid}/publish", headers=auth,
                    json={"connector": "linkedin", "dry_run": False})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["went_live"] is False  # gate overrides the request
    assert body["dry_run"] is True


def test_publish_unknown_connector_422(client, auth):
    aid = _make_approved_draft(client, auth)
    r = client.post(f"/api/v1/govcon/approvals/{aid}/publish", headers=auth,
                    json={"connector": "myspace"})
    assert r.status_code == 422


def test_connectors_include_noop(client, auth):
    r = client.get("/api/v1/govcon/connectors", headers=auth)
    assert r.status_code == 200
    assert "noop" in r.json()["connectors"]


def test_publish_records_analytics_event(client, auth):
    aid = _make_approved_draft(client, auth)
    client.post(f"/api/v1/govcon/approvals/{aid}/publish", headers=auth,
                json={"connector": "noop"})
    ev = client.get(
        "/api/v1/govcon/analytics/events?event_type=draft_published_or_marked_ready",
        headers=auth).json()
    assert any(e["metadata"].get("approval_id") == aid for e in ev["events"])


# ─── GA4 conversion: no-op provider ───────────────────────────────────────────

def test_ga4_measurement_is_noop_without_credentials():
    from echo.integrations import ga4_measurement
    assert ga4_measurement.is_configured() is False
    res = ga4_measurement.send_event(client_id="c", name="cta_click", params={"x": 1})
    assert res["sent"] is False and res["reason"] == "not_configured"


def test_cta_click_tracking_records_event(client, auth):
    r = client.post("/api/v1/govcon/track/cta-click", headers=auth,
                    json={"campaign": "govcon_daily_brief", "url": "https://x/y"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["conversion"] == "cta_click"
    assert body["ga4"]["sent"] is False  # GA4 not configured in tests
    ev = client.get("/api/v1/govcon/analytics/events?event_type=conversion_cta_click",
                    headers=auth).json()
    assert ev["count"] >= 1


def test_cta_click_requires_auth(client):
    assert client.post("/api/v1/govcon/track/cta-click",
                       json={"campaign": "x"}).status_code == 401


# ─── NRS / SEMA: mock + disabled behavior ─────────────────────────────────────

def test_nrs_disabled_returns_empty_by_default():
    from echo.integrations import nrs
    assert nrs.is_configured() is False
    assert nrs.get_procurement_signals() == []  # no URL, no mock flag → empty


def test_nrs_mock_signals_are_labelled():
    from echo.integrations import nrs
    sigs = nrs.mock_signals(state="TX", limit=5)
    assert sigs and all(s["mock"] is True and s["provider"] == "nrs" for s in sigs)
    assert all("[MOCK]" in s["title"] for s in sigs)


def test_sema_disabled_returns_empty_by_default():
    from echo.integrations import sema
    assert sema.is_configured() is False
    assert sema.get_procurement_signals() == []


def test_disaster_provider_status(client, auth):
    r = client.get("/api/v1/govcon/disaster/status", headers=auth)
    assert r.status_code == 200, r.text
    providers = r.json()["providers"]
    assert providers["fema"] == "live"
    assert providers["nrs"] == "disabled"   # no URL, no mock
    assert providers["sema"] == "disabled"


# ─── Sturgeon handoff conversion metadata ─────────────────────────────────────

def test_handoff_records_conversion_event(client, auth):
    h = client.post("/api/v1/govcon/sturgeon/handoff", headers=auth,
                    json={"opportunity_title": "Conv Test", "agency": "VA"}).json()
    ev = client.get("/api/v1/govcon/analytics/events?event_type=conversion_sturgeon_handoff",
                    headers=auth).json()
    assert any(e["metadata"].get("handoff_id") == h["id"] for e in ev["events"])
