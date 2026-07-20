# Echo Core

Standalone Railway-deployable GovCon automation backend.

## Services

| Service | Command |
|---------|---------|
| **Echo Web** | `uvicorn echo.main:app --host 0.0.0.0 --port $PORT` |
| **Echo Worker** | `python -m echo.worker` |

Both services share the same codebase and the same Railway Postgres database. Deploy the Web service first (it runs `create_tables()` on startup).

## Required Environment Variables

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection string (injected by Railway Postgres plugin) |
| `ECHO_API_KEY` | Secret key for API authentication |

## Optional Environment Variables

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Enables AI content generation via Claude |
| `ANTHROPIC_MODEL` | Claude model to use (default: `claude-3-5-haiku-20241022`) |
| `SAM_GOV_API_KEY` | SAM.gov contract opportunity search |
| `BUFFER_API_KEY` | Buffer social scheduling (access token) |
| `BUFFER_PROFILE_IDS` | Comma-separated Buffer profile ids to target (default: first connected) |
| `LINKEDIN_ACCESS_TOKEN` | LinkedIn publishing |
| `LINKEDIN_AUTHOR_URN` | LinkedIn author URN (`urn:li:person:...`) |
| `SLACK_WEBHOOK_URL` | Slack notifications |
| `GA4_PROPERTY_ID` | GA4 property id for campaign click/conversion attribution |
| `GA4_ACCESS_TOKEN` | OAuth2 bearer token for the GA4 Data API (read-only) |
| `IMAGE_API_KEY` | OpenAI-compatible images API key (auto Instagram image) |
| `VIDEO_API_KEY` + `VIDEO_API_URL` | External render service for TikTok video (`{script,voice}` → `{video_url}`) |
| `SUPABASE_URL` + `SUPABASE_SERVICE_KEY` + `MEDIA_BUCKET` | Host generated images at a public URL (for base64 image responses) |
| `ECHO_ALLOW_LIVE_PUBLISH` | Set to `true` to enable live publishing (default: dry-run only) |
| `ECHO_ENABLED` | Set to `false` to disable workflow scheduling (default: `true`) |
| `ECHO_SCHEDULE_<SLUG>` | Override a scheduled workflow's cadence in seconds (`0` disables) |
| `ECHO_RLS_ENABLED` | Scope DB sessions to their tenant for opt-in RLS (default: `false`; pair with `SELECT echo_enable_rls();`) |
| `NRS_API_URL` / `SEMA_API_URL` | Extra disaster feeds folded into FEMA (safe no-op when unset) |
| `WORKER_TICK_INTERVAL` | Worker scheduler interval in seconds (default: `60`) |
| `CORS_ORIGINS` | Comma-separated allowed origins (default: `*`) |

## API Authentication

All endpoints except `GET /api/v1/health` require authentication.

Pass one of:
- Header: `x-echo-key: <ECHO_API_KEY>`
- Header: `Authorization: Bearer <ECHO_API_KEY>`

## API Endpoints

```
GET  /api/v1/health                          # Unauthenticated health check
GET  /api/v1/workflows                       # List registered workflows
POST /api/v1/workflows/{slug}/run            # Trigger a workflow
GET  /api/v1/runs                            # List workflow runs
GET  /api/v1/runs/{run_id}                   # Get a workflow run
GET  /api/v1/approvals                       # List pending approvals
POST /api/v1/approvals/{approval_id}/decide  # Approve or reject
GET  /api/v1/content                         # Content cockpit
GET  /api/v1/publishing-jobs                 # Publishing job cockpit
GET  /api/v1/logs                            # Automation logs
GET  /api/v1/integration-health              # Integration health
GET  /api/v1/analytics/summary               # Aggregate analytics
```

Interactive docs at `/docs`.

## Registered Workflows

| Slug | Name |
|------|------|
| `weekly_report` | Weekly GovCon Report |
| `govcon_daily_intelligence` | GovCon Daily Intelligence Briefing |
| `linkedin_signal_post` | LinkedIn Signal Post |
| `fema_disaster_monitor` | FEMA Disaster Monitor |
| `sam_opportunity_watch` | SAM.gov Opportunity Watch |
| `approved_publisher` | Approved Publisher |
| `content_calendar_archive` | Content Calendar Archive |
| `prospect_dm` | Prospect DM Generator |
| `strategic_comment` | Strategic Comment Generator |
| `social_post` | Multi-Platform Social Post (LinkedIn/Facebook/Instagram/TikTok) |
| `produce_media` | Produce Media Asset (Instagram image / TikTok video) |

## Railway Deployment

> 📘 **For a full, step-by-step go-live runbook** (migrations, env vars, smoke
> checks, the publish-gate flip, troubleshooting) see **[DEPLOY.md](DEPLOY.md)**.

### Deploy Echo Web

1. Connect this repo in the Railway dashboard
2. Set all required env vars in the Railway service settings
3. Add a Postgres plugin — Railway injects `DATABASE_URL` automatically
4. Deploy — `railway.json` configures the start command and health check

### Add Echo Worker (second service)

In the Railway project, add a second service from the same repo with start command:
```
python -m echo.worker
```
Share the same env vars (no separate Postgres needed — same `DATABASE_URL`).

## Pre-deploy Validation

```bash
pip install -r requirements.txt
python verify_golive.py
```

## Tests

A hermetic smoke suite drives the real FastAPI app against a throwaway SQLite
database in dry-run mode (no Postgres, Railway, or live API keys needed). It
covers the auth gate, workflow execution, the approval→publish lifecycle, every
cockpit read endpoint, and the analytics summary.

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest -q
```

## Database Migrations

Run in Supabase SQL Editor (or via `supabase db push`):
1. `supabase/migrations/0001_echo_core_schema.sql` — workflow_runs, approvals
2. `supabase/migrations/0002_cockpit_read_models.sql` — content_items, publishing_jobs, automation_logs, integration_health
3. `supabase/migrations/0003_echo_jobs.sql` — echo_jobs, echo_job_schedules, echo_execution_audits
4. `supabase/migrations/0004_echo_govcon.sql` — echo_workflows, echo_analytics_events, echo_sturgeon_handoffs, compatibility views
5. `supabase/migrations/0005_id_type_reconciliation.sql` — align id columns (UUID→TEXT) with the ORM
6. `supabase/migrations/0006_multitenant_rls.sql` — opt-in multi-tenant RLS (`SELECT echo_enable_rls();`)

All migrations are idempotent and safe to re-run.

## Security

- Secrets are read from environment variables only — never hardcoded
- Live publishing is gated behind `ECHO_ALLOW_LIVE_PUBLISH=true` (default: dry-run)
- The backend has no dependency on frontend code
