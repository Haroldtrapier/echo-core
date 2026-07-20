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

## Recently closed (completion pass)

- [x] **Scheduled cadence wiring** — scheduled workflows now auto-run on the
      worker tick when their cadence is due. Each carries a
      `schedule_interval_seconds` (daily brief = 86 400s, FEMA watch = 3 600s,
      weekly tracker = 604 800s), overridable per deploy with
      `ECHO_SCHEDULE_<SLUG>` (seconds; `0` disables). Surfaced in the registry
      metadata. Fixed a latent worker crash (`scheduler.tick` now accepts the
      worker's session and the tick report's failed-count is used correctly).
      Covered by `tests/test_scheduler_and_disaster.py`.
- [x] **Live NRS/SEMA disaster adapters** — `echo/integrations/nrs.py` and
      `echo/integrations/sema.py` implement the FEMA `get_disaster_declarations`
      shape, normalize records into the FEMA field layout, and activate when
      `NRS_API_URL` / `SEMA_API_URL` (+ optional `*_API_KEY`) are set — otherwise
      they contribute nothing. `pack.safe_disaster_declarations` fans out across
      FEMA + NRS + SEMA, de-duplicates, and is consumed by the daily brief and
      procurement watch.
- [x] **Id-type drift reconciliation** — `supabase/migrations/0005_id_type_reconciliation.sql`
      converts every `UUID` id column across the schema to `TEXT` to match the
      ORM's 32-char hex ids. Generic (catalog-driven, covers future id columns),
      idempotent, non-lossy, and FK-safe (captures/recreates every foreign key
      verbatim, preserving `ON DELETE` semantics). Verified end-to-end on
      Postgres 16: 0 uuid columns remain, all FKs preserved, cascade intact,
      re-runnable. This supersedes the earlier "workflow_runs.id / approvals.id"
      note — the drift was schema-wide.

## Remaining gaps (to reach truly 100%)

- [ ] **Live connector send** on `mark-ready` (LinkedIn/email) — currently
      publishing still runs through `approved_publisher` in dry-run until
      `ECHO_ALLOW_LIVE_PUBLISH=true` and real connector creds exist. (Config +
      credentials, not missing code.)
- [ ] **CTA click attribution** — depends on GA4 being configured
      (`GA4_PROPERTY_ID` / `GA4_ACCESS_TOKEN`); the weekly tracker notes this.
- [x] **Multi-tenant RLS** — migration `0006_multitenant_rls.sql` installs
      idempotent `echo_enable_rls()` / `echo_disable_rls()` functions (catalog-
      driven over every `tenant_id` table). Applying the migration is a no-op;
      enable with `SELECT echo_enable_rls();` (reversible). The app scopes each
      session to its tenant via `app.current_tenant` when `ECHO_RLS_ENABLED=true`
      (no-op on SQLite / for the owner role). Proven on Postgres 16: a non-owner
      role sees only its tenant's rows (+ shared `NULL`-tenant rows), the owner
      bypasses (never locked out), cross-tenant writes are blocked, and
      enable/disable are idempotent. Left `ECHO_RLS_ENABLED=false` by default so
      single-tenant deployments are unaffected until isolation is turned on.
- [ ] **Live end-to-end validation** — exercise the real SAM.gov / LinkedIn /
      Buffer / FEMA calls once credentials are provisioned (all paths degrade
      safely without them today).

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
supabase/migrations/0004_echo_govcon.sql
supabase/migrations/0005_id_type_reconciliation.sql   ← id UUID→TEXT reconciliation
supabase/migrations/0006_multitenant_rls.sql          ← opt-in tenant RLS (echo_enable_rls())
```

`0004` adds `echo_workflows`, `echo_analytics_events`, `echo_sturgeon_handoffs`,
and extends `approvals` + `workflow_runs`. The app also calls
`create_tables()` (SQLAlchemy `create_all`) on startup, so a fresh DB is
self-provisioning; the SQL migrations are for Supabase-managed environments.

## Deployment steps

1. Provision Postgres (Railway plugin or Supabase). Apply migrations `0001`–`0006`.
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

## Production smoke test runner

`scripts/smoke_echo_govcon_prod.sh` runs the full Echo GovCon production loop
against a deployed instance and prints a PASS/FAIL summary with a GO/NO-GO exit
code (`0` = GO, `1` = NO-GO, `2` = usage error). Run it from a shell that has
network egress to the Railway service (e.g. your machine or a `railway run`
shell):

```bash
BASE=https://<echo>.up.railway.app ECHO_API_KEY=<production key> \
  bash scripts/smoke_echo_govcon_prod.sh
```

Requires `bash`, `curl`, and `jq`. It fails fast if `BASE` or `ECHO_API_KEY` is
missing and never prints the API key.

It checks, in order: (1) health, (2) db-health (masked DB host + `echo_` tables),
(3) protected route without key → 401, (4) with key → 200, (5)
`live_publishing_enabled=false`, (6) GovCon registry lists the 6 pack workflows,
(7) run `govcon_daily_brief`, (8) run record persisted, (9) approval draft
created, (10) approve the draft, (11) `draft_approved` analytics event, (12)
create a Sturgeon handoff, (13) handoff record logged, (14)
`sturgeon_handoff_created` analytics event, (15) run `weekly_performance_tracker`,
(16) no auto-publish (0 published + live publishing off).

**Production-safety:** it never enables live publishing and asserts it stays off;
it only creates review drafts + one intake handoff (both labelled `[SMOKE TEST]`)
and approves a draft (status/analytics only — approval does **not** publish). It
does write a small number of rows (one run, one draft, one handoff, analytics
events) to the connected DB — inherent to an end-to-end smoke test. If
`STURGEON_API_URL` is configured server-side, the `[SMOKE TEST]` handoff is
forwarded to Sturgeon's intake (never touching billing/credits/human-review);
delete that record afterward.

## Known limitations

- AI copy is placeholder text unless `ANTHROPIC_API_KEY` is set (workflows still
  succeed and produce structured, reviewable drafts).
- Live external calls (SAM.gov/USASpending/FEMA) require network + keys; without
  them briefs render with "no live signals" sections rather than failing.
- Live publishing and Sturgeon forwarding are opt-in via env — off by default so
  no content or handoff leaves the system unintentionally.
