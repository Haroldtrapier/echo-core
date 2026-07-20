"""Scheduler cadence + multi-source disaster feed tests.

Covers the gaps closed in the completion pass:

* the worker/scheduler tick (``core.scheduler.tick``) now accepts a session,
  auto-runs scheduled workflows when their cadence is due, and does not re-run
  them before the interval elapses;
* ``ECHO_SCHEDULE_<SLUG>`` overrides / disables a cadence;
* the NRS and SEMA adapters normalize to the FEMA declaration shape and no-op
  safely when unconfigured;
* ``pack.safe_disaster_declarations`` aggregates + de-duplicates across sources.

All hermetic — no network, no live keys (matches conftest's SQLite dry-run app).
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from echo.core import scheduler
from echo.db import WorkflowRun, db_session
from echo.integrations import nrs, sema
from echo.workflows.govcon import pack


# ─── Scheduler cadence ────────────────────────────────────────────────────────

def test_tick_runs_due_scheduled_workflows_then_holds(_init_db):
    """First tick fires every scheduled workflow; an immediate second tick fires none."""
    with db_session() as db:
        first = scheduler.tick(db)
    # The three GovCon scheduled workflows should all be due on a cold DB.
    assert {"govcon_daily_brief", "fema_procurement_watch",
            "weekly_performance_tracker"} <= set(first.scheduled)
    assert first.failed_count == 0

    with db_session() as db:
        second = scheduler.tick(db)
    # None are due again immediately (their cadence has not elapsed).
    assert second.scheduled == []
    assert second.failed_count == 0


def test_tick_reruns_when_cadence_elapsed(_init_db):
    """A scheduled workflow becomes due again once its interval has passed."""
    with db_session() as db:
        scheduler.tick(db)  # establishes a last-run for each scheduled slug

    # Backdate the FEMA watch's last scheduler run beyond its 1h cadence.
    with db_session() as db:
        runs = (
            db.query(WorkflowRun)
            .filter(
                WorkflowRun.workflow_slug == "fema_procurement_watch",
                WorkflowRun.triggered_by == "scheduler",
            )
            .all()
        )
        assert runs, "expected a scheduler-triggered fema run"
        for r in runs:
            r.created_at = r.created_at - timedelta(hours=2)
        db.commit()

    with db_session() as db:
        again = scheduler.tick(db)
    assert "fema_procurement_watch" in again.scheduled
    # The daily/weekly ones are not due yet.
    assert "weekly_performance_tracker" not in again.scheduled


def test_resolve_schedule_seconds_env_override(monkeypatch):
    from echo.core.registry import get_workflow

    cls = get_workflow("govcon_daily_brief")
    assert scheduler.resolve_schedule_seconds(cls) == 86_400  # class default

    monkeypatch.setenv("ECHO_SCHEDULE_GOVCON_DAILY_BRIEF", "120")
    assert scheduler.resolve_schedule_seconds(cls) == 120

    monkeypatch.setenv("ECHO_SCHEDULE_GOVCON_DAILY_BRIEF", "0")  # disable
    assert scheduler.resolve_schedule_seconds(cls) is None


def test_tick_without_session_opens_its_own(_init_db):
    """tick() with no argument manages its own DB session (worker-less callers)."""
    report = scheduler.tick()
    assert report.failed_count == 0


# ─── NRS / SEMA adapters ──────────────────────────────────────────────────────

def test_nrs_sema_no_op_when_unconfigured(monkeypatch):
    monkeypatch.setattr(nrs, "NRS_API_URL", "", raising=False)
    monkeypatch.setattr(sema, "SEMA_API_URL", "", raising=False)
    assert nrs.configured() is False
    assert sema.configured() is False
    assert nrs.get_disaster_declarations(state="TX") == []
    assert sema.get_disaster_declarations(state="TX") == []


def test_nrs_normalizes_to_fema_shape():
    raw = {"type": "Flood", "stateCode": "TX", "title": "Severe Flooding",
           "date": "2026-07-01", "number": "DR-1234"}
    out = nrs.normalize(raw)
    assert out["source"] == "nrs"
    assert out["incidentType"] == "Flood"
    assert out["state"] == "TX"
    assert out["declarationTitle"] == "Severe Flooding"
    assert out["declarationDate"] == "2026-07-01"
    assert out["declarationNumber"] == "DR-1234"
    assert out["raw"] is raw


def test_sema_normalize_falls_back_to_arg_state():
    out = sema.normalize({"hazard": "Wildfire", "headline": "County Fire"}, state="CA")
    assert out["source"] == "sema"
    assert out["incidentType"] == "Wildfire"
    assert out["declarationTitle"] == "County Fire"
    assert out["state"] == "CA"  # not in record → filled from arg


def test_safe_disaster_declarations_aggregates_and_dedupes(monkeypatch):
    def fema_stub(*, state=None, limit=5, days_back=14):
        return [{"incidentType": "Hurricane", "state": "FL",
                 "declarationNumber": "DR-9", "declarationTitle": "Storm"}]

    def nrs_stub(*, state=None, limit=5, days_back=14):
        # Duplicate of the FEMA record (same state/type/number) + a unique one.
        return [
            {"source": "nrs", "incidentType": "Hurricane", "state": "FL",
             "declarationNumber": "DR-9", "declarationTitle": "Storm"},
            {"source": "nrs", "incidentType": "Flood", "state": "FL",
             "declarationNumber": "DR-10", "declarationTitle": "Flood"},
        ]

    import echo.integrations.fema as fema_mod
    monkeypatch.setattr(fema_mod, "get_disaster_declarations", fema_stub)
    monkeypatch.setattr(nrs, "get_disaster_declarations", nrs_stub)
    monkeypatch.setattr(sema, "get_disaster_declarations",
                        lambda **k: [])  # SEMA contributes nothing

    merged = pack.safe_disaster_declarations(state="FL", limit=10)
    keys = {(d["incidentType"], d.get("declarationNumber")) for d in merged}
    assert ("Hurricane", "DR-9") in keys
    assert ("Flood", "DR-10") in keys
    assert len(merged) == 2  # the duplicate Hurricane/DR-9 was collapsed


def test_safe_disaster_declarations_survives_source_error(monkeypatch):
    import echo.integrations.fema as fema_mod

    def boom(**kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr(fema_mod, "get_disaster_declarations", boom)
    monkeypatch.setattr(nrs, "get_disaster_declarations", lambda **k: [])
    monkeypatch.setattr(sema, "get_disaster_declarations", lambda **k: [])
    # A raising source must not propagate — the aggregate degrades to [].
    assert pack.safe_disaster_declarations(state="TX") == []
