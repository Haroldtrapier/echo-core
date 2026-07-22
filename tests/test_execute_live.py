"""Execute-path tests: approval gate, live-publish gate, and real dispatch.

Uses the shared conftest harness (SQLite, dry-run default, authed TestClient).
LinkedIn is stubbed — no network calls, no real posts.
"""
from __future__ import annotations

import pytest


def _make_job(client, auth, **overrides):
    payload = {"title": "Test post", "channel": "linkedin", "body": "Hello from Echo"}
    payload.update(overrides)
    r = client.post("/api/v1/echo/jobs", json=payload, headers=auth)
    assert r.status_code in (200, 201), r.text
    return r.json()


def _approve_job(client, auth, job_id: str) -> None:
    """draft → dry_run → pending_approval, then approve directly in the DB."""
    assert client.post(f"/api/v1/echo/jobs/{job_id}/dry-run", headers=auth).status_code == 200
    assert (
        client.post(
            f"/api/v1/echo/jobs/{job_id}/request-approval",
            json={"reason": "test"},
            headers=auth,
        ).status_code
        == 200
    )
    import echo.db as edb

    with edb.SessionLocal() as db:
        job = db.query(edb.EchoJob).filter(edb.EchoJob.id == job_id).first()
        approval = db.query(edb.Approval).filter(edb.Approval.id == job.approval_id).first()
        approval.status = "approved"
        db.commit()


def test_execute_blocked_without_approval(client, auth):
    job = _make_job(client, auth)
    r = client.post(f"/api/v1/echo/jobs/{job['id']}/execute", headers=auth)
    assert r.status_code == 403
    assert "approval" in r.json()["detail"].lower()


def test_execute_blocked_when_live_publish_disabled(client, auth):
    # conftest guarantees ECHO_ALLOW_LIVE_PUBLISH is unset → gate must block.
    job = _make_job(client, auth)
    _approve_job(client, auth, job["id"])
    r = client.post(f"/api/v1/echo/jobs/{job['id']}/execute", headers=auth)
    assert r.status_code == 403
    assert "ECHO_ALLOW_LIVE_PUBLISH" in r.json()["detail"]


def test_execute_publishes_live_when_gates_pass(client, auth, monkeypatch):
    import echo.api.echo_routes as routes
    import echo.modules.publisher as publisher
    import echo.integrations.linkedin as li

    monkeypatch.setattr(routes, "ECHO_ALLOW_LIVE_PUBLISH", True)
    monkeypatch.setattr(publisher, "ECHO_ALLOW_LIVE_PUBLISH", True)

    posted: dict = {}

    def _fake_li_post(content):
        posted.update(content)
        return "https://www.linkedin.com/feed/update/urn:li:share:123"

    monkeypatch.setattr(li, "post", _fake_li_post)

    job = _make_job(client, auth)
    _approve_job(client, auth, job["id"])
    r = client.post(f"/api/v1/echo/jobs/{job['id']}/execute", headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "published"
    assert (
        body["job_metadata"]["live_publish"]["live_url"]
        == "https://www.linkedin.com/feed/update/urn:li:share:123"
    )
    assert posted["body"] == "Hello from Echo"

    audit = client.get(
        f"/api/v1/echo/jobs/{job['id']}/execution-audit", headers=auth
    ).json()
    assert audit[0]["result"] == "published_live"


def test_execute_marks_failed_on_publish_error(client, auth, monkeypatch):
    import echo.api.echo_routes as routes
    import echo.modules.publisher as publisher
    import echo.integrations.linkedin as li

    monkeypatch.setattr(routes, "ECHO_ALLOW_LIVE_PUBLISH", True)
    monkeypatch.setattr(publisher, "ECHO_ALLOW_LIVE_PUBLISH", True)

    def _boom(content):
        raise RuntimeError("LINKEDIN_ACCESS_TOKEN not configured")

    monkeypatch.setattr(li, "post", _boom)

    job = _make_job(client, auth)
    _approve_job(client, auth, job["id"])
    r = client.post(f"/api/v1/echo/jobs/{job['id']}/execute", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "failed"
    assert "LINKEDIN_ACCESS_TOKEN" in body["job_metadata"]["live_publish"]["error"]

    audit = client.get(
        f"/api/v1/echo/jobs/{job['id']}/execution-audit", headers=auth
    ).json()
    assert audit[0]["result"] == "publish_failed"


def test_execute_503_when_publisher_forces_dry_run(client, auth, monkeypatch):
    """Route gate open but publisher module still dry-run → 503, not silent no-op."""
    import echo.api.echo_routes as routes
    import echo.modules.publisher as publisher

    monkeypatch.setattr(routes, "ECHO_ALLOW_LIVE_PUBLISH", True)
    monkeypatch.setattr(publisher, "ECHO_ALLOW_LIVE_PUBLISH", False)

    job = _make_job(client, auth)
    _approve_job(client, auth, job["id"])
    r = client.post(f"/api/v1/echo/jobs/{job['id']}/execute", headers=auth)
    assert r.status_code == 503
    assert "mismatch" in r.json()["detail"].lower()
