"""End-to-end smoke test for Echo Core.

Drives the real FastAPI app against a throwaway SQLite DB in dry-run mode and
exercises the full operating path the cockpit/Imani depend on:

    auth gate → list workflows → run a workflow → inspect runs →
    approval lifecycle (request → list → decide → publish) →
    every cockpit read endpoint → analytics summary.

These cases cover the "still being finished" checklist items: authenticated
/workflows, workflow execution, approval queue, and the publishing path.
"""
from __future__ import annotations


# ─── Auth + health ──────────────────────────────────────────────────────────

def test_health_is_unauthenticated(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_workflows_requires_auth(client):
    assert client.get("/api/v1/workflows").status_code == 401


def test_workflows_listed_with_key(client, auth):
    r = client.get("/api/v1/workflows", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 7
    slugs = {w["slug"] for w in body["workflows"]}
    assert "linkedin_signal_post" in slugs
    assert "approved_publisher" in slugs


# ─── Workflow execution ───────────────────────────────────────────────────────

def test_run_linkedin_signal_post_dry_run(client, auth):
    r = client.post(
        "/api/v1/workflows/linkedin_signal_post/run",
        headers=auth,
        json={"payload": {"topic": "CMMC 2.0 readiness for small contractors"},
              "triggered_by": "smoke"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "succeeded"
    assert body["result"]["dry_run"] is True
    assert body["result"]["post_text"]
    assert body["message"]
    # recorded and retrievable
    run_id = body["run_id"]
    assert client.get(f"/api/v1/runs/{run_id}", headers=auth).status_code == 200
    listing = client.get("/api/v1/runs", headers=auth).json()
    assert listing["total"] >= 1


def test_validation_returns_422(client, auth):
    r = client.post("/api/v1/workflows/linkedin_signal_post/run",
                    headers=auth, json={"payload": {}})
    assert r.status_code == 422
    assert "topic" in r.text


def test_unknown_workflow_returns_404(client, auth):
    r = client.post("/api/v1/workflows/does_not_exist/run",
                    headers=auth, json={"payload": {}})
    assert r.status_code == 404


# ─── Approval lifecycle + publishing path ─────────────────────────────────────

def test_approval_gate_then_publish(client, auth):
    # 1. First run creates a pending approval (nothing is published)
    r1 = client.post(
        "/api/v1/workflows/approved_publisher/run",
        headers=auth,
        json={"payload": {"platform": "linkedin",
                          "content": {"body": "Approved-only GovCon post"},
                          "requested_by": "harold@company.com"}},
    )
    assert r1.status_code == 200, r1.text
    approval_id = r1.json()["result"]["approval_id"]
    assert r1.json()["result"]["status"] == "pending"

    # 2. It shows up in the approval queue
    pending = client.get("/api/v1/approvals", headers=auth).json()
    assert any(a["id"] == approval_id for a in pending["approvals"])

    # 3. Approve it
    d = client.post(
        f"/api/v1/approvals/{approval_id}/decide",
        headers=auth,
        json={"decision": "approved", "decision_by": "harold", "note": "looks good"},
    )
    assert d.status_code == 200
    assert d.json()["status"] == "approved"

    # 4. Re-run with the approval id → publishes (dry-run; nothing live leaves)
    r2 = client.post(
        "/api/v1/workflows/approved_publisher/run",
        headers=auth,
        json={"payload": {"platform": "linkedin",
                          "content": {"body": "Approved-only GovCon post"},
                          "approval_id": approval_id}},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["status"] == "succeeded"


def test_rejected_approval_blocks_publish(client, auth):
    r1 = client.post(
        "/api/v1/workflows/approved_publisher/run",
        headers=auth,
        json={"payload": {"platform": "linkedin", "content": {"body": "Nope"}}},
    )
    approval_id = r1.json()["result"]["approval_id"]
    client.post(f"/api/v1/approvals/{approval_id}/decide", headers=auth,
                json={"decision": "rejected", "decision_by": "harold"})
    r2 = client.post(
        "/api/v1/workflows/approved_publisher/run",
        headers=auth,
        json={"payload": {"platform": "linkedin", "content": {"body": "Nope"},
                          "approval_id": approval_id}},
    )
    # workflow ran, but result reflects the rejection (not published)
    assert r2.status_code == 200
    assert r2.json()["status"] == "failed"


# ─── Cockpit read endpoints (power the Imani dashboard) ───────────────────────

def test_cockpit_endpoints_respond(client, auth):
    for path in ("/api/v1/content", "/api/v1/publishing-jobs",
                 "/api/v1/logs", "/api/v1/integration-health"):
        r = client.get(path, headers=auth)
        assert r.status_code == 200, f"{path} -> {r.status_code}: {r.text}"


def test_analytics_summary(client, auth):
    r = client.get("/api/v1/analytics/summary", headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "workflows" in body
    assert body["workflows"]["total_runs"] >= 1


# ─── Network-free workflows succeed end-to-end ────────────────────────────────
# (linkedin_signal_post + approved_publisher are covered above. fema /
# usaspending / govcon_daily_intelligence reach external APIs and are exercised
# manually, not in the hermetic suite.)

import pytest  # noqa: E402


@pytest.mark.parametrize("slug,payload", [
    ("weekly_report", {}),
    ("content_calendar_archive", {"dry_run": True}),
    ("sam_opportunity_watch", {"keywords": "information technology", "limit": 3}),
])
def test_network_free_workflows_succeed(client, auth, slug, payload):
    r = client.post(f"/api/v1/workflows/{slug}/run",
                    headers=auth, json={"payload": payload})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "succeeded", r.text
