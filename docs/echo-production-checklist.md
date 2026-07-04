# Echo / Echo GovCon — Production Checklist

Status of the Echo Core + Echo GovCon production MVP.

## Completed

- [x] **Workflow registry** — in-code registry + `echo_workflows` DB mirror with all
      required metadata fields; `GET /api/v1/govcon/workflows/registry`.
- [x] **Run lifecycle + retry engine** — `workflow_runs` with `retry_count`,
      `max_retries`, `completed_at`, `tenant_id`, `user_id`; inline retries.
- [x] **Triggers** — manual (`/workflows/{slug}/run`), webhook (`/webhooks/{slug}`),
      scheduled (worker tick + `/echo/scheduler/tick`).
- [x] **Approval queue** — draft approvals (`draft_type`, `draft_content`,
      `reviewed_by`, `reviewed_at`); list/read/edit/approve/reject/mark-ready API +
      `cockpit/approvals.html` admin page.
- [x] **Analytics event stream** — `echo_analytics_events` + `record_event()` wired
      into runner, approvals, handoffs, and lead nurture; query API.
- [x] **Sturgeon handoff** — `echo_sturgeon_handoffs` + `create_handoff()` + API,
      with optional live forward and safe local-pending fallback.
- [x] **Echo GovCon pack (A–F)** — daily brief, opportunity-to-content, FEMA watch,
      certification education, lead nurture, weekly performance tracker.
- [x] **Security** — API-key auth on all non-health routes; approval-first;
      `ECHO_ALLOW_LIVE_PUBLISH` kill-switch; no client secrets; billing untouched.
- [x] **Tests** — 56 passing (existing smoke suite + new `tests/test_govcon.py`).
- [x] **Docs** — `docs/echo-core.md`, `docs/echo-govcon.md`, this checklist.
- [x] **Migration** — `supabase/migrations/0004_echo_govcon.sql`.
- [x] **`.env.example`** — all vars with safe fallbacks.

## Remaining gaps (to reach truly 100%)

- [ ] **Live connector send** on `mark-ready` (LinkedIn/email) — currently
      publishing still runs through `approved_publisher` in dry-run until
      `ECHO_ALLOW_LIVE_PUBLISH=true` and real connector creds exist.
- [ ] **Live NRS/SEMA disaster adapters** — FEMA is live; NRS/SEMA use the safe
      mockable interface (`pack.safe_fema_declarations`) with TODO markers.
- [ ] **CTA click attribution** — depends on GA4 being configured
      (`GA4_PROPERTY_ID` / `GA4_ACCESS_TOKEN`); the weekly tracker notes this.
- [ ] **Scheduled cadence wiring** — scheduled workflows run on the worker tick;
      define the concrete cron/interval per workflow in the deploy env.
- [ ] **Multi-tenant RLS** — Echo is single-tenant-by-default (`DEFAULT_TENANT_ID`);
      tenant columns exist but Supabase RLS policies are not enabled (the existing
      migrations use no RLS — matching project convention).
- [ ] **Pre-existing id-type drift (follow-up, not introduced here)** — in the
      hand-written SQL migrations `workflow_runs.id` / `approvals.id` are `UUID`,
      while the runtime ORM uses `VARCHAR(32)` hex ids. The app provisions its
      schema via `create_all()` (ORM types), so this only affects environments
      that apply the SQL migrations standalone. Reconciling it is a destructive
      PK-type change on shipped tables and should be a dedicated migration, not
      bundled here.

## Table names

The five Echo tables: `echo_workflows`, `echo_analytics_events`, and
`echo_sturgeon_handoffs` are dedicated tables; runs and approvals reuse the
pre-existing `workflow_runs` / `approvals` tables (extended in place, no
duplication). Migration `0004` adds read-through compatibility views
`echo_workflow_runs` and `echo_approvals` so all five spec names resolve. Verified
idempotent + view creation on Postgres 16 (0001→0004, then re-run 0004).

## Environment variables

Required in production: `ECHO_API_KEY`, `DATABASE_URL` (Railway/Supabase-injected).
Recommended: `ANTHROPIC_API_KEY` (real AI copy vs. placeholder).
Optional (enable features): `STURGEON_API_URL` + `STURGEON_API_KEY` (forward
handoffs), `SAM_GOV_API_KEY`, `SLACK_WEBHOOK_URL`, `BUFFER_API_KEY`,
`LINKEDIN_*`, `GA4_*`, media/storage keys, `ECHO_ALLOW_LIVE_PUBLISH=true`.
All are optional for build/test — see `.env.example`.

## Database migrations

Run in order against Supabase/Postgres (idempotent):

```
supabase/migrations/0001_echo_core_schema.sql
supabase/migrations/0002_cockpit_read_models.sql
supabase/migrations/0003_echo_jobs.sql
supabase/migrations/0004_echo_govcon.sql   ← new (this MVP)
```

`0004` adds `echo_workflows`, `echo_analytics_events`, `echo_sturgeon_handoffs`,
and extends `approvals` + `workflow_runs`. The app also calls
`create_tables()` (SQLAlchemy `create_all`) on startup, so a fresh DB is
self-provisioning; the SQL migrations are for Supabase-managed environments.

## Deployment steps

1. Provision Postgres (Railway plugin or Supabase). Apply migrations `0001`–`0004`.
2. Set env vars (at minimum `ECHO_API_KEY`; `DATABASE_URL` is auto-injected on Railway).
3. Deploy the web service: `uvicorn echo.main:app --host 0.0.0.0 --port $PORT`
   (see `railway.json` / `DEPLOY.md`).
4. Deploy the worker: `python -m echo.worker` (ticks the scheduler every
   `WORKER_TICK_INTERVAL` seconds).
5. Verify: `GET /api/v1/health` (200), `GET /api/v1/db-health` (lists echo tables),
   `GET /api/v1/govcon/workflows/registry` (17 workflows).
6. Open `cockpit/approvals.html`, connect with the API base + key, and run the loop.

## Test commands

```bash
pip install -r requirements.txt -r requirements-dev.txt
python verify_golive.py        # import + registry + DB gate (CI pre-deploy check)
pytest -q                      # full suite (hermetic SQLite, dry-run)
```

## Known limitations

- AI copy is placeholder text unless `ANTHROPIC_API_KEY` is set (workflows still
  succeed and produce structured, reviewable drafts).
- Live external calls (SAM.gov/USASpending/FEMA) require network + keys; without
  them briefs render with "no live signals" sections rather than failing.
- Live publishing and Sturgeon forwarding are opt-in via env — off by default so
  no content or handoff leaves the system unintentionally.
