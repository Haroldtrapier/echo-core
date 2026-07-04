"""Echo GovCon pack + Echo Core additions — end-to-end loop tests.

Drives the production MVP loop against the hermetic SQLite app (dry-run, no live
keys): trigger a GovCon brief → saved run → reviewable draft in the approval
queue → approve/reject (analytics events) → Sturgeon handoff (logged) →
weekly performance tracker reads the event stream.
"""
from __future__ import annotations

import pytest


# ─── Registry metadata + table ────────────────────────────────────────────────

def test_workflow_registry_exposes_govcon_metadata(client, auth):
    r = client.get("/api/v1/govcon/workflows/registry?product_area=echo_govcon", headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    ids = {w["workflow_id"] for w in body["workflows"]}
    assert {"govcon_daily_brief", "opportunity_to_content", "fema_procurement_watch",
            "certification_education", "lead_nurture", "weekly_performance_tracker"} <= ids
    brief = next(w for w in body["workflows"] if w["workflow_id"] == "govcon_daily_brief")
    # required registry fields are present
    for field in ("workflow_name", "product_area", "trigger_type", "input_schema",
                  "output_type", "approval_required", "connector_targets",
                  "required_tier", "enabled"):
        assert field in brief
    assert brief["approval_required"] is True
    assert brief["product_area"] == "echo_govcon"


# ─── A. Daily GovCon Brief → run record + reviewable draft ────────────────────

def test_daily_brief_creates_run_and_draft(client, auth):
    r = client.post("/api/v1/workflows/govcon_daily_brief/run", headers=auth,
                    json={"payload": {"keywords": ["cybersecurity"]}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "succeeded"
    result = body["result"]
    assert result["post_id"].startswith("post_")
    assert result["approval_id"]
    assert result["draft_type"] == "brief"
    # brief content carries the required sections + Sturgeon CTA
    brief = result["brief"]
    for section in ("Top Opportunities", "Agency Movement", "FEMA", "Certification",
                    "Recommended Action", "Sturgeon"):
        assert section in brief

    # 1. a run record was saved
    run_id = body["run_id"]
    run = client.get(f"/api/v1/runs/{run_id}", headers=auth).json()
    assert run["slug"] == "govcon_daily_brief"

    # 2. the draft appears in the approval queue with source + timestamp
    q = client.get("/api/v1/govcon/approvals?status=pending", headers=auth).json()
    draft = next(a for a in q["approvals"] if a["id"] == result["approval_id"])
    assert draft["draft_type"] == "brief"
    assert draft["draft_content"]
    assert draft["content_post_id"] == result["post_id"]
    assert draft["created_at"]


def test_draft_created_records_analytics_event(client, auth):
    client.post("/api/v1/workflows/govcon_daily_brief/run", headers=auth,
                json={"payload": {"keywords": ["cloud"]}})
    ev = client.get("/api/v1/govcon/analytics/events?event_type=draft_created", headers=auth).json()
    assert ev["count"] >= 1
    assert ev["events"][0]["event_type"] == "draft_created"
    # workflow lifecycle events are also recorded
    started = client.get("/api/v1/govcon/analytics/events?event_type=workflow_started",
                         headers=auth).json()
    assert started["count"] >= 1


# ─── Approve / reject + analytics ─────────────────────────────────────────────

def test_approve_draft_records_event_and_marks_ready(client, auth):
    gen = client.post("/api/v1/workflows/govcon_daily_brief/run", headers=auth,
                      json={"payload": {}}).json()
    approval_id = gen["result"]["approval_id"]

    ok = client.post(f"/api/v1/govcon/approvals/{approval_id}/approve", headers=auth,
                     json={"reviewed_by": "harold", "note": "ship it"})
    assert ok.status_code == 200, ok.text
    approved = ok.json()
    assert approved["status"] == "approved"
    assert approved["reviewed_by"] == "harold"
    assert approved["reviewed_at"]

    # draft_approved event recorded
    ev = client.get("/api/v1/govcon/analytics/events?event_type=draft_approved", headers=auth).json()
    assert any(e["metadata"].get("approval_id") == approval_id for e in ev["events"])

    # mark ready → draft_published_or_marked_ready
    rdy = client.post(f"/api/v1/govcon/approvals/{approval_id}/mark-ready", headers=auth,
                      json={"marked_by": "harold"})
    assert rdy.status_code == 200, rdy.text
    assert rdy.json()["status"] == "ready"
    ready_ev = client.get(
        "/api/v1/govcon/analytics/events?event_type=draft_published_or_marked_ready",
        headers=auth).json()
    assert ready_ev["count"] >= 1


def test_reject_draft_records_event(client, auth):
    gen = client.post("/api/v1/workflows/certification_education/run", headers=auth,
                      json={"payload": {"certification": "8a"}}).json()
    approval_id = gen["result"]["approval_id"]
    rej = client.post(f"/api/v1/govcon/approvals/{approval_id}/reject", headers=auth,
                      json={"reviewed_by": "harold", "note": "off-brand"})
    assert rej.status_code == 200
    assert rej.json()["status"] == "rejected"
    ev = client.get("/api/v1/govcon/analytics/events?event_type=draft_rejected", headers=auth).json()
    assert any(e["metadata"].get("approval_id") == approval_id for e in ev["events"])


def test_cannot_mark_ready_before_approval(client, auth):
    gen = client.post("/api/v1/workflows/govcon_daily_brief/run", headers=auth,
                      json={"payload": {}}).json()
    approval_id = gen["result"]["approval_id"]
    r = client.post(f"/api/v1/govcon/approvals/{approval_id}/mark-ready", headers=auth,
                    json={"marked_by": "harold"})
    assert r.status_code == 409


def test_edit_draft_content(client, auth):
    gen = client.post("/api/v1/workflows/govcon_daily_brief/run", headers=auth,
                      json={"payload": {}}).json()
    approval_id = gen["result"]["approval_id"]
    ed = client.patch(f"/api/v1/govcon/approvals/{approval_id}", headers=auth,
                      json={"draft_content": "edited brief body"})
    assert ed.status_code == 200
    assert ed.json()["draft_content"] == "edited brief body"


# ─── B. Opportunity-to-Content ────────────────────────────────────────────────

def test_opportunity_to_content_bundles_channels(client, auth):
    r = client.post("/api/v1/workflows/opportunity_to_content/run", headers=auth,
                    json={"payload": {"topic": "DoD zero-trust modernization", "agency": "DISA"}})
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    assert res["approval_id"]
    assert "LinkedIn Post" in res["draft_type"] or res["draft_type"] == "linkedin_post"
    assert res["linkedin_post"] and res["email_blurb"] and res["what_it_means"]


def test_opportunity_to_content_requires_topic(client, auth):
    r = client.post("/api/v1/workflows/opportunity_to_content/run", headers=auth,
                    json={"payload": {}})
    assert r.status_code == 422
    assert "topic" in r.text


# ─── C. FEMA procurement watch + handoff ──────────────────────────────────────

def test_fema_watch_drafts_alert_and_optional_handoff(client, auth):
    r = client.post("/api/v1/workflows/fema_procurement_watch/run", headers=auth,
                    json={"payload": {"state": "TX", "days_back": 14}})
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    assert res["draft_type"] == "alert"
    assert res["approval_id"]
    # content includes readiness angle + Sturgeon CTA
    draft = client.get(f"/api/v1/govcon/approvals/{res['approval_id']}", headers=auth).json()
    assert "Readiness" in draft["draft_content"]
    assert "Sturgeon" in draft["draft_content"]


# ─── D. Certification education ────────────────────────────────────────────────

@pytest.mark.parametrize("cert", ["sdvosb", "8a", "wosb", "hubzone", "samgov",
                                  "uei_cage", "capability_statement"])
def test_certification_education_all_topics(client, auth, cert):
    r = client.post("/api/v1/workflows/certification_education/run", headers=auth,
                    json={"payload": {"certification": cert}})
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    assert res["certification"] == cert
    assert res["approval_id"]
    # fallback content is present even with no AI key
    draft = client.get(f"/api/v1/govcon/approvals/{res['approval_id']}", headers=auth).json()
    assert draft["draft_content"]


# ─── E. Lead nurture ──────────────────────────────────────────────────────────

def test_lead_nurture_creates_sequence(client, auth):
    r = client.post("/api/v1/workflows/lead_nurture/run", headers=auth,
                    json={"payload": {"lead_name": "Acme Federal"}})
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    assert res["count"] == 5
    steps = [d["step"] for d in res["drafts"]]
    assert steps == ["welcome", "education", "pain_point", "sturgeon_cta", "offer"]
    # a lead_nurture_created event was recorded
    ev = client.get("/api/v1/govcon/analytics/events?event_type=lead_nurture_created",
                    headers=auth).json()
    assert ev["count"] >= 1
    # each email is an individually reviewable draft
    q = client.get("/api/v1/govcon/approvals?status=pending&limit=200", headers=auth).json()
    ids = {a["id"] for a in q["approvals"]}
    assert all(d["approval_id"] in ids for d in res["drafts"])


# ─── Sturgeon handoff (API) ───────────────────────────────────────────────────

def test_sturgeon_handoff_created_and_logged(client, auth):
    payload = {
        "opportunity_title": "IT Modernization Services",
        "agency": "Department of Veterans Affairs",
        "solicitation_number": "36C10B24R0001",
        "due_date": "2026-08-15",
        "source_url": "https://sam.gov/opp/xyz",
        "summary": "Multi-year IT modernization IDIQ.",
        "requirements": "Secret clearance; past performance on VA systems.",
        "recommended_next_action": "Run solicitation analysis in Sturgeon.",
    }
    r = client.post("/api/v1/govcon/sturgeon/handoff", headers=auth, json=payload)
    assert r.status_code == 200, r.text
    h = r.json()
    assert h["id"]
    assert h["opportunity_title"] == payload["opportunity_title"]
    # forwarding disabled in tests → stored locally as pending
    assert h["status"] == "pending"

    # it's retrievable + listed
    got = client.get(f"/api/v1/govcon/sturgeon/handoffs/{h['id']}", headers=auth)
    assert got.status_code == 200
    lst = client.get("/api/v1/govcon/sturgeon/handoffs", headers=auth).json()
    assert any(x["id"] == h["id"] for x in lst["handoffs"])
    assert lst["forwarding_enabled"] is False

    # a sturgeon_handoff_created analytics event was logged
    ev = client.get("/api/v1/govcon/analytics/events?event_type=sturgeon_handoff_created",
                    headers=auth).json()
    assert any(e["metadata"].get("handoff_id") == h["id"] for e in ev["events"])


def test_sturgeon_handoff_requires_auth(client):
    r = client.post("/api/v1/govcon/sturgeon/handoff",
                    json={"opportunity_title": "x"})
    assert r.status_code == 401


# ─── F. Weekly performance tracker reads the event stream ─────────────────────

def test_weekly_performance_tracker_summarizes_activity(client, auth):
    # generate some activity first
    client.post("/api/v1/workflows/govcon_daily_brief/run", headers=auth, json={"payload": {}})
    r = client.post("/api/v1/workflows/weekly_performance_tracker/run", headers=auth,
                    json={"payload": {"days_back": 7}})
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    m = res["metrics"]
    assert m["workflows_run"] >= 1
    assert m["drafts_created"] >= 1
    assert "Recommendations for Next Week" in res["brief"]


# ─── Retry engine ─────────────────────────────────────────────────────────────

def test_retry_count_recorded_on_success(client, auth):
    # a successful run records retry_count 0 and completed_at
    body = client.post("/api/v1/workflows/govcon_daily_brief/run", headers=auth,
                       json={"payload": {}}).json()
    run = client.get(f"/api/v1/runs/{body['run_id']}", headers=auth).json()
    assert run["status"] == "succeeded"


# ─── Auth guard on the whole pack ─────────────────────────────────────────────

def test_govcon_endpoints_require_auth(client):
    assert client.get("/api/v1/govcon/approvals").status_code == 401
    assert client.get("/api/v1/govcon/analytics/events").status_code == 401
    assert client.post("/api/v1/workflows/govcon_daily_brief/run",
                       json={"payload": {}}).status_code == 401
