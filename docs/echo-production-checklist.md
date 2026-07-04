# Echo / Echo GovCon — Production Checklist

Status of the Echo Core + Echo GovCon production MVP.

## ⛔ BLOCKED: dedicated Echo production database

Echo Core **must run on its own database**, separate from Sturgeon.

- **Do NOT use the `sturgeon-ai` Supabase project for Echo migrations.** It is the
  live Sturgeon production database — it holds `users`, `profiles`, `subscriptions`,
  `proposals`, `proposal_credits`, `proposal_purchases`, `proposal_reviews`,
  `human_review_requests`. Echo's migrations create generic `workflow_runs` /
  `approvals` tables and `CREATE OR REPLACE` a shared `set_updated_at` trigger
  function that Sturgeon's tables depend on — applying them there would modify
  protected Sturgeon infrastructure. **Prohibited.**
- **Current blocker:** creating the dedicated `echo-core-prod` Supabase project is
  blocked by the org's **2-active-free-project limit** (Trapier Management LLC).
  Resolve by upgrading the org to Supabase Pro (recommended — free projects also
  auto-pause after ~7 days idle, unsuitable for production) or freeing a slot
  (do **not** pause `sturgeon-ai`).

### Final database steps (once the project limit is resolved)
1. Create dedicated project `echo-core-prod`.
2. Apply `0001 → 0002 → 0003 → 0004 → 0005` in order (idempotent, additive).
3. Run the verification query (see "Post-migration verification" below).
4. Set Railway `DATABASE_URL` to the new project; keep `ECHO_ALLOW_LIVE_PUBLISH=false`.
5. Redeploy; run `scripts/smoke_echo_govcon_prod.sh`.

## Phase 2 scaffolding (flag-gated — all OFF by default)

Implemented behind safe switches; nothing production-impacting is on by default.

| Feature | Flag / default | Guard |
| --- | --- | --- |
| Recurring schedules (daily brief, weekly tracker) | `ECHO_SCHEDULER_ENABLED=false` | double-gated: global flag **and** per-row `enabled` |
| Approval-first publishing + connectors | dry-run default | live only if approval approved/ready **and** `ECHO_ALLOW_LIVE_PUBLISH=true` |
| GA4 conversion tracking (Measurement Protocol) | `GA4_MEASUREMENT_ID`/`GA4_API_SECRET` unset | no-op provider; analytics still recorded |
| NRS / SEMA disaster adapters | `NRS_API_URL`/`SEMA_API_URL` unset | disabled → `[]`; `*_USE_MOCK=true` for labelled mock only |

New migration `0005_echo_scheduler.sql` (table `echo_schedules`) — apply to the
dedicated Echo DB only, **not** to `sturgeon-ai`.

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
supabase/migrations/0004_echo_govcon.sql   ← MVP (PR #7)
supabase/migrations/0005_echo_scheduler.sql ← Phase 2 (echo_schedules)
```

> Apply to the **dedicated Echo database only** — never to `sturgeon-ai`.

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
