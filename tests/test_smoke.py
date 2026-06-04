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

import pytest


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
    assert body["count"] == 11
    slugs = {w["slug"] for w in body["workflows"]}
    assert {"linkedin_signal_post", "approved_publisher", "prospect_dm",
            "strategic_comment", "social_post", "produce_media"} <= slugs


# ─── Workflow execution ───────────────────────────────────────────────────────

def test_linkedin_signal_post_queues_a_draft(client, auth):
    r = client.post(
        "/api/v1/workflows/linkedin_signal_post/run",
        headers=auth,
        json={"payload": {"topic": "CMMC 2.0 readiness for small contractors",
                          "brand": "Apex GovCon", "campaign": "cmmc_push"},
              "triggered_by": "smoke"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "succeeded"
    result = body["result"]
    assert result["post_text"]
    assert result["post_id"].startswith("post_")
    assert result["status"] == "pending_review"
    assert result["approved"] is False and result["published"] is False
    assert "utm_campaign=cmmc_push" in result["cta_url"]

    # run recorded + the draft shows up in the Content Queue
    run_id = body["run_id"]
    assert client.get(f"/api/v1/runs/{run_id}", headers=auth).status_code == 200
    content = client.get("/api/v1/content?status=pending_review", headers=auth).json()
    assert any(i["post_id"] == result["post_id"] for i in content["items"])


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


def test_draft_to_publish_populates_queues(client, auth):
    """End-to-end: generate draft → approve → publish → cockpit rows land."""
    # 1. Generate a draft via LinkedIn Signal Post
    gen = client.post(
        "/api/v1/workflows/linkedin_signal_post/run", headers=auth,
        json={"payload": {"topic": "SDVOSB set-aside opportunities"}},
    ).json()
    post_id = gen["result"]["post_id"]

    # 2. Request approval for that specific post
    req = client.post(
        "/api/v1/workflows/approved_publisher/run", headers=auth,
        json={"payload": {"platform": "linkedin", "post_id": post_id}},
    ).json()
    approval_id = req["result"]["approval_id"]
    assert req["result"]["status"] == "pending"

    # 3. Approve
    client.post(f"/api/v1/approvals/{approval_id}/decide", headers=auth,
                json={"decision": "approved", "decision_by": "harold"})

    # 4. Publish (dry-run) referencing the same post_id
    pub = client.post(
        "/api/v1/workflows/approved_publisher/run", headers=auth,
        json={"payload": {"platform": "linkedin", "post_id": post_id,
                          "approval_id": approval_id}},
    ).json()
    assert pub["status"] == "succeeded"
    assert pub["result"]["publishing_job_id"]

    # 5. A publishing job row exists; content item is now approved (dry-run → not live)
    jobs = client.get("/api/v1/publishing-jobs", headers=auth).json()
    assert any(j["post_id"] == post_id for j in jobs["jobs"])
    content = client.get("/api/v1/content?status=approved", headers=auth).json()
    item = next(i for i in content["items"] if i["post_id"] == post_id)
    assert item["approved"] is True
    assert item["published"] is False  # dry-run never claims a live publish


def test_scheduled_publish_threads_scheduling_metadata(client, auth):
    """A scheduled publish records scheduling intent (still dry-run while gated)."""
    gen = client.post("/api/v1/workflows/linkedin_signal_post/run", headers=auth,
                      json={"payload": {"topic": "GSA Schedule basics"}}).json()
    post_id = gen["result"]["post_id"]
    req = client.post("/api/v1/workflows/approved_publisher/run", headers=auth,
                      json={"payload": {"platform": "buffer", "post_id": post_id}}).json()
    approval_id = req["result"]["approval_id"]
    client.post(f"/api/v1/approvals/{approval_id}/decide", headers=auth,
                json={"decision": "approved", "decision_by": "harold"})
    pub = client.post("/api/v1/workflows/approved_publisher/run", headers=auth,
                      json={"payload": {"platform": "buffer", "post_id": post_id,
                                        "approval_id": approval_id,
                                        "scheduled_at": "2030-01-01T09:00:00Z"}}).json()
    assert pub["status"] == "succeeded"
    assert pub["result"]["scheduled"] is True
    assert pub["result"]["scheduled_at"] == "2030-01-01T09:00:00Z"
    # live publishing is gated off in tests, so the actual job stays dry_run
    assert pub["result"]["dry_run"] is True
    jobs = client.get("/api/v1/publishing-jobs?platform=buffer", headers=auth).json()
    assert any(j["post_id"] == post_id for j in jobs["jobs"])


@pytest.mark.parametrize("platform,ctype", [
    ("linkedin", "linkedin_post"),
    ("facebook", "facebook_post"),
])
def test_social_post_text_networks_queue_drafts(client, auth, platform, ctype):
    r = client.post("/api/v1/workflows/social_post/run", headers=auth,
                    json={"payload": {"platform": platform, "topic": "DoD cloud spending"}})
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    assert res["content_type"] == ctype
    assert res["status"] == "pending_review"
    assert res["needs_media"] is False


def test_instagram_without_image_is_flagged_needs_media(client, auth):
    r = client.post("/api/v1/workflows/social_post/run", headers=auth,
                    json={"payload": {"platform": "instagram", "topic": "SDVOSB wins"}})
    res = r.json()["result"]
    assert res["status"] == "needs_media"
    assert res["needs_media"] is True and res["media_kind"] == "image"


def test_instagram_with_image_is_publishable(client, auth):
    r = client.post("/api/v1/workflows/social_post/run", headers=auth,
                    json={"payload": {"platform": "instagram", "topic": "SDVOSB wins",
                                      "image_url": "https://cdn.example/post.jpg"}})
    res = r.json()["result"]
    assert res["status"] == "pending_review"
    assert res["needs_media"] is False
    # the image rides through approval → publish (dry-run here)
    post_id = res["post_id"]
    req = client.post("/api/v1/workflows/approved_publisher/run", headers=auth,
                      json={"payload": {"platform": "instagram", "post_id": post_id}}).json()
    aid = req["result"]["approval_id"]
    client.post(f"/api/v1/approvals/{aid}/decide", headers=auth,
                json={"decision": "approved", "decision_by": "harold"})
    pub = client.post("/api/v1/workflows/approved_publisher/run", headers=auth,
                      json={"payload": {"platform": "instagram", "post_id": post_id,
                                        "approval_id": aid}}).json()
    assert pub["status"] == "succeeded"


def test_tiktok_generates_script_and_requires_video(client, auth):
    r = client.post("/api/v1/workflows/social_post/run", headers=auth,
                    json={"payload": {"platform": "tiktok", "topic": "8(a) program 101"}})
    res = r.json()["result"]
    assert res["content_type"] == "tiktok_video"
    assert res["needs_media"] is True and res["media_kind"] == "video"
    assert res["text"]  # a script was produced


def test_social_post_rejects_unknown_platform(client, auth):
    r = client.post("/api/v1/workflows/social_post/run", headers=auth,
                    json={"payload": {"platform": "myspace", "topic": "x"}})
    assert r.status_code == 422
    assert "platform" in r.text


# ─── Media generation (Instagram image / TikTok video) ───────────────────────

def test_media_generators_degrade_without_providers():
    from echo.modules import image_generator, video_generator
    assert image_generator.is_configured() is False
    assert image_generator.generate_image("topic") is None
    v = video_generator.generate_video("a script")
    assert v["status"] == "needs_production" and v["video_url"] is None


def test_produce_media_reports_needs_production_without_provider(client, auth):
    gen = client.post("/api/v1/workflows/social_post/run", headers=auth,
                      json={"payload": {"platform": "instagram", "topic": "GSA wins"}}).json()
    post_id = gen["result"]["post_id"]
    r = client.post("/api/v1/workflows/produce_media/run", headers=auth,
                    json={"payload": {"post_id": post_id}})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["status"] == "failed"  # workflow ran, asset not produced
    assert res["result"]["status"] == "needs_media"
    assert res["result"]["provider_configured"] is False


def test_produce_media_attaches_image_when_provider_present(client, auth, monkeypatch):
    # Simulate a configured image provider returning a hosted URL.
    from echo.modules import image_generator
    monkeypatch.setattr(image_generator, "generate_image",
                        lambda *a, **k: "https://cdn.example/generated.png")

    gen = client.post("/api/v1/workflows/social_post/run", headers=auth,
                      json={"payload": {"platform": "instagram", "topic": "8(a) basics"}}).json()
    post_id = gen["result"]["post_id"]
    assert gen["result"]["status"] == "needs_media"

    prod = client.post("/api/v1/workflows/produce_media/run", headers=auth,
                       json={"payload": {"post_id": post_id}}).json()
    assert prod["status"] == "succeeded"
    assert prod["result"]["image_url"].endswith("generated.png")
    assert prod["result"]["status"] == "pending_review"

    # the draft is now publishable (dry-run)
    item = next(i for i in client.get("/api/v1/content?status=pending_review",
                headers=auth).json()["items"] if i["post_id"] == post_id)
    assert item["status"] == "pending_review"


def test_social_post_auto_media_video_needs_production(client, auth):
    # auto_media with no video provider → still needs_media, with production detail
    r = client.post("/api/v1/workflows/social_post/run", headers=auth,
                    json={"payload": {"platform": "tiktok", "topic": "CMMC tips",
                                      "auto_media": True}}).json()
    res = r["result"]
    assert res["needs_media"] is True
    assert res["media_production"]["status"] == "needs_production"


def test_asset_storage_degrades_without_config():
    from echo.modules import asset_storage
    assert asset_storage.is_configured() is False
    assert asset_storage.upload_bytes(b"\x89PNG...", content_type="image/png") is None


def test_image_generator_hosts_base64_via_storage(monkeypatch):
    """A base64 image response is hosted via asset_storage and returns a real URL."""
    import json as _json

    from echo.modules import asset_storage, image_generator

    monkeypatch.setattr(image_generator, "is_configured", lambda: True)

    class _Resp:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return _json.dumps({"data": [{"b64_json": "aGk="}]}).encode()

    monkeypatch.setattr(image_generator.urllib.request, "urlopen", lambda *a, **k: _Resp())
    monkeypatch.setattr(asset_storage, "upload_bytes",
                        lambda *a, **k: "https://store.example/echo/abc.png")

    assert image_generator.generate_image("CMMC tips") == "https://store.example/echo/abc.png"


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
    assert body["ga4_configured"] is False  # no GA4 creds in test env


def test_ga4_degrades_gracefully_without_credentials():
    from echo.integrations import ga4
    assert ga4.is_configured() is False
    assert ga4.get_campaign_metrics(["any_campaign"]) == {}


def test_weekly_report_includes_campaign_attribution(client, auth):
    # Seed a campaign by generating a post (creates ContentItem w/ utm_campaign)
    client.post("/api/v1/workflows/linkedin_signal_post/run", headers=auth,
                json={"payload": {"topic": "8(a) program basics", "campaign": "attr_demo"}})
    r = client.post("/api/v1/workflows/weekly_report/run", headers=auth, json={"payload": {}})
    assert r.status_code == 200, r.text
    attribution = r.json()["result"]["attribution"]
    assert attribution["ga4_configured"] is False
    assert "attr_demo" in attribution["campaigns"]
    # DB inventory present even though GA4 metrics are zero (no creds)
    assert attribution["campaigns"]["attr_demo"]["content_items"] >= 1
    assert attribution["campaigns"]["attr_demo"]["sessions"] == 0.0


# ─── Network-free workflows succeed end-to-end ────────────────────────────────
# (linkedin_signal_post + approved_publisher are covered above. fema /
# usaspending / govcon_daily_intelligence reach external APIs and are exercised
# manually, not in the hermetic suite.)


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


# ─── Outreach Engine: prospect DM + strategic comment (approval-first) ────────

def test_prospect_dm_queues_draft(client, auth):
    r = client.post(
        "/api/v1/workflows/prospect_dm/run", headers=auth,
        json={"payload": {"prospect_name": "Jane Doe", "company": "Acme Federal",
                          "role": "Capture Manager", "angle": "SAM.gov teaming"}},
    )
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    assert res["status"] == "pending_review"
    assert res["dm_text"]
    content = client.get("/api/v1/content?status=pending_review", headers=auth).json()
    item = next(i for i in content["items"] if i["post_id"] == res["post_id"])
    assert item["content_type"] == "prospect_dm"
    assert item["published"] is False


def test_prospect_dm_requires_name(client, auth):
    r = client.post("/api/v1/workflows/prospect_dm/run", headers=auth,
                    json={"payload": {}})
    assert r.status_code == 422
    assert "prospect_name" in r.text


def test_strategic_comment_queues_draft(client, auth):
    r = client.post(
        "/api/v1/workflows/strategic_comment/run", headers=auth,
        json={"payload": {"post_context": "A post about CMMC 2.0 deadlines slipping",
                          "angle": "reassure small contractors", "post_url": "https://x/y"}},
    )
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    assert res["status"] == "pending_review"
    assert res["comment_text"]
    content = client.get("/api/v1/content", headers=auth).json()
    assert any(i["post_id"] == res["post_id"]
               and i["content_type"] == "strategic_comment" for i in content["items"])


def test_outreach_drafts_are_approvable_and_publishable(client, auth):
    """A DM draft flows through the same approval→publish gate as posts."""
    gen = client.post("/api/v1/workflows/prospect_dm/run", headers=auth,
                      json={"payload": {"prospect_name": "John Roe"}}).json()
    post_id = gen["result"]["post_id"]
    req = client.post("/api/v1/workflows/approved_publisher/run", headers=auth,
                      json={"payload": {"platform": "linkedin", "post_id": post_id}}).json()
    approval_id = req["result"]["approval_id"]
    client.post(f"/api/v1/approvals/{approval_id}/decide", headers=auth,
                json={"decision": "approved", "decision_by": "harold"})
    pub = client.post("/api/v1/workflows/approved_publisher/run", headers=auth,
                      json={"payload": {"platform": "linkedin", "post_id": post_id,
                                        "approval_id": approval_id}}).json()
    assert pub["status"] == "succeeded"
    jobs = client.get("/api/v1/publishing-jobs", headers=auth).json()
    assert any(j["post_id"] == post_id for j in jobs["jobs"])
