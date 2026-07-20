"""Approved-draft dispatch bridge + email connector.

Exercises the loop closure added in the completion pass: an approved GovCon draft
is sent through its connector (LinkedIn / email) via
``POST /api/v1/govcon/approvals/{id}/send``. Hermetic + dry-run (no live keys,
``ECHO_ALLOW_LIVE_PUBLISH`` never set) so nothing actually leaves the system.
"""
from __future__ import annotations

from echo.integrations import email_resend
from echo.modules import dispatch


def _run_and_approve(client, auth, slug: str, payload: dict) -> str:
    gen = client.post(f"/api/v1/workflows/{slug}/run", headers=auth,
                      json={"payload": payload}).json()
    approval_id = gen["result"]["approval_id"]
    ok = client.post(f"/api/v1/govcon/approvals/{approval_id}/approve", headers=auth,
                     json={"reviewed_by": "harold"})
    assert ok.status_code == 200, ok.text
    return approval_id


# ─── LinkedIn draft → send (dry-run) ──────────────────────────────────────────

def test_send_linkedin_draft_dry_run(client, auth):
    approval_id = _run_and_approve(
        client, auth, "opportunity_to_content", {"topic": "SDVOSB set-asides"})
    r = client.post(f"/api/v1/govcon/approvals/{approval_id}/send", headers=auth,
                    json={"sent_by": "harold"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["platform"] == "linkedin"
    assert body["dry_run"] is True          # gate off → forced dry-run
    assert body["success"] is True
    assert body["status"] == "sent"
    assert body["publishing_job_id"]

    # the send is recorded as a publishing job
    jobs = client.get("/api/v1/publishing-jobs?platform=linkedin", headers=auth).json()
    assert any(str(j["id"]) == str(body["publishing_job_id"]) for j in jobs["jobs"])

    # and a draft_published_or_marked_ready analytics event was emitted
    ev = client.get(
        "/api/v1/govcon/analytics/events?event_type=draft_published_or_marked_ready",
        headers=auth).json()
    assert any(e["metadata"].get("approval_id") == approval_id for e in ev["events"])


# ─── Email draft → requires a recipient, then sends ───────────────────────────

def test_send_email_draft_requires_recipient_then_sends(client, auth):
    approval_id = _run_and_approve(
        client, auth, "certification_education", {"topic": "WOSB"})

    missing = client.post(f"/api/v1/govcon/approvals/{approval_id}/send", headers=auth,
                          json={"sent_by": "harold"})
    assert missing.status_code == 422  # email needs a recipient

    sent = client.post(f"/api/v1/govcon/approvals/{approval_id}/send", headers=auth,
                       json={"sent_by": "harold", "recipient": "lead@example.com"})
    assert sent.status_code == 200, sent.text
    body = sent.json()
    assert body["platform"] == "email"
    assert body["dry_run"] is True
    assert body["status"] == "sent"


# ─── Guard rails ──────────────────────────────────────────────────────────────

def test_send_unknown_approval_404(client, auth):
    r = client.post("/api/v1/govcon/approvals/does-not-exist/send", headers=auth,
                    json={"sent_by": "harold"})
    assert r.status_code == 404


def test_send_unapproved_draft_conflicts(client, auth):
    gen = client.post("/api/v1/workflows/opportunity_to_content/run", headers=auth,
                      json={"payload": {"topic": "8(a)"}}).json()
    approval_id = gen["result"]["approval_id"]  # still pending, not approved
    r = client.post(f"/api/v1/govcon/approvals/{approval_id}/send", headers=auth,
                    json={"sent_by": "harold"})
    assert r.status_code == 409


def test_brief_is_not_sendable(client, auth):
    approval_id = _run_and_approve(
        client, auth, "govcon_daily_brief", {"keywords": ["cyber"]})
    r = client.post(f"/api/v1/govcon/approvals/{approval_id}/send", headers=auth,
                    json={"sent_by": "harold"})
    assert r.status_code == 422  # briefs are internal reports, not sends


# ─── Email connector unit behavior ────────────────────────────────────────────

def test_email_connector_unconfigured_is_not_configured(monkeypatch):
    monkeypatch.setattr(email_resend, "RESEND_API_KEY", "", raising=False)
    monkeypatch.setattr(email_resend, "EMAIL_FROM", "", raising=False)
    assert email_resend.configured() is False


def test_dispatch_sendable_platform_mapping():
    assert dispatch.sendable_platform("linkedin_post") == "linkedin"
    assert dispatch.sendable_platform("email") == "email"
    assert dispatch.sendable_platform("brief") is None
    assert dispatch.sendable_platform(None) is None
