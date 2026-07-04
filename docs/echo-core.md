# Echo Core

Echo Core is the **automation runtime** behind the GovCon Command Center, Sturgeon
AI, and Imani/Apex OS. It is a FastAPI + SQLAlchemy service that turns registered
workflows into auditable, approval-gated runs, records every step as analytics, and
never publishes AI-generated content without a human decision.

## What Echo Core is

- A **workflow registry** (in-code, mirrored to a DB table)
- A **runner** with a retry engine and a full run lifecycle
- A **trigger surface**: manual (API), scheduled (worker tick), and webhook
- An **approval queue** for the approval-first content model
- An **analytics event stream** (the source of truth for "what happened")
- A **connector execution** abstraction (Slack, Buffer, LinkedIn, SAM.gov, FEMA, …)
- A **Sturgeon handoff** bridge into proposal execution

Everything degrades safely without credentials: missing API keys produce mock /
dry-run behavior so local build and test never need real secrets.

## Architecture

```
             ┌──────────── FastAPI app (echo.main) ────────────┐
 triggers →  │  /workflows/{slug}/run     (manual)             │
 (api /      │  /webhooks/{slug}          (webhook)            │
  worker /   │  worker.py → core.scheduler.tick (scheduled)    │
  webhook)   └───────────────┬─────────────────────────────────┘
                             │ run_workflow()
                    ┌────────▼─────────┐   emits    ┌─────────────────────┐
                    │ core.runner      │──────────► │ echo_analytics_events│
                    │ (retry engine)   │            └─────────────────────┘
                    └────────┬─────────┘
                             │ instance.run(db, payload)
                    ┌────────▼─────────┐
                    │ BaseWorkflow     │ creates ContentItem + draft Approval
                    │ (echo.workflows) │ (approval-first) → connectors on approve
                    └────────┬─────────┘
                             │
        ┌────────────────────┼───────────────────────┐
        ▼                    ▼                        ▼
  approval queue      Sturgeon handoff          cockpit read models
  (echo_approvals)   (echo_sturgeon_handoffs)  (content/publishing/logs)
```

Key modules:

| Path | Responsibility |
| --- | --- |
| `echo/core/registry.py` | Register workflows; `sync_registry()` mirrors to `echo_workflows` |
| `echo/core/runner.py` | Run lifecycle, retry engine, workflow analytics events |
| `echo/core/scheduler.py` | Worker tick — picks up pending runs |
| `echo/core/workflow.py` | `BaseWorkflow` + registry metadata fields |
| `echo/modules/approval.py` | Draft + publish-gate approvals, decide, edit, mark-ready |
| `echo/modules/events.py` | `record_event()` + queries over the event stream |
| `echo/modules/sturgeon.py` | `create_handoff()` + optional forward to Sturgeon |
| `echo/api/routes.py` | Core API (`/api/v1`) |
| `echo/api/govcon_routes.py` | Approval queue, Sturgeon, analytics, registry (`/api/v1/govcon`) |

## Workflow registry

Workflows subclass `BaseWorkflow` and are registered with `@register`. Registry
metadata (mirrored to the `echo_workflows` table by `sync_registry` on startup):

| Field | Meaning |
| --- | --- |
| `workflow_id` (`slug`) | Unique id used in the API |
| `workflow_name` (`name`) | Display name |
| `product_area` | `echo_core` \| `echo_govcon` \| … |
| `description` | One-liner |
| `trigger_type` | `manual` \| `scheduled` \| `webhook` \| `event` |
| `input_schema` | Advisory payload shape |
| `output_type` | `draft` \| `brief` \| `report` \| `alert` \| `handoff` \| `media` \| `none` |
| `approval_required` | Output must pass the approval queue |
| `connector_targets` | Integrations the workflow may write to |
| `required_tier` | `free` \| `starter` \| `pro` \| `enterprise` |
| `enabled` | Runnable/surfaced |

Read it at `GET /api/v1/govcon/workflows/registry`.

## Run lifecycle

`run_workflow()` creates a `workflow_runs` row and drives it through:

```
running → (succeeded | completed)          # workflow returned success
running → retrying → running (≤ max_retries)
running → failed                            # exception or unsuccessful result
```

Run fields: `id`, `workflow_slug`, `tenant_id`, `user_id`, `status`,
`payload`, `result`, `error`, `retry_count`, `max_retries`, `created_at`,
`updated_at`, `completed_at`. The runner injects `_run_id` / `_tenant_id` /
`_user_id` into the workflow payload so workflows can link drafts and handoffs
back to their run without changing the `run()` signature.

**Retry engine:** `max_retries` comes from the workflow class attr, the payload
(`max_retries`), or defaults to 0. Retries run inline and deterministically, so
the API caller receives the final outcome; `retry_count` counts retries consumed
(0 = only the initial attempt ran).

## Approval queue

The approval-first model: workflows create a **draft** (`ContentItem` +
`Approval` with `draft_type` + `draft_content`), never publishing on their own.

Approval fields: `id`, `run_id` (`workflow_run_id`), `status`
(`pending` → `approved`/`rejected` → `ready`), `draft_type`
(`brief` \| `linkedin_post` \| `email` \| `alert` \| `handoff`), `draft_content`,
`content_post_id`, `reviewed_by`, `reviewed_at`, `created_at`, `updated_at`.

API (`/api/v1/govcon`): `GET /approvals`, `GET /approvals/{id}`,
`PATCH /approvals/{id}` (edit), `POST /approvals/{id}/approve`,
`POST /approvals/{id}/reject`, `POST /approvals/{id}/mark-ready`.
Admin UI: `cockpit/approvals.html`.

## Analytics

Every state transition writes one immutable `echo_analytics_events` row via
`events.record_event()`. Event types: `workflow_started`, `workflow_completed`,
`workflow_failed`, `draft_created`, `draft_approved`, `draft_rejected`,
`draft_published_or_marked_ready`, `sturgeon_handoff_created`,
`lead_nurture_created`. Each event carries `event_type`, `workflow_id`,
`workflow_run_id`, `user_id`, `tenant_id`, `metadata`, `created_at`.

Read: `GET /api/v1/govcon/analytics/events` (filter by type/workflow/tenant/window).
The aggregate `GET /api/v1/analytics/summary` remains for cockpit dashboards.

Recording is **best-effort** — a failed analytics write never breaks the workflow.

## Security rules

- **Auth:** all non-health endpoints require `x-echo-key` or `Authorization: Bearer`.
  When `ECHO_API_KEY` is unset, auth is disabled (dev only — set it in prod).
- **No client secrets:** all provider keys are server-side env vars.
- **No auto-publish:** AI content is never published without an approved decision;
  live publishing is additionally gated behind `ECHO_ALLOW_LIVE_PUBLISH` (default off).
- **Billing untouched:** Echo only creates intake records for Sturgeon; it never
  modifies proposal credits, Stripe, or human-review purchase logic.
- **Validation + errors:** workflows validate payloads (422 on bad input);
  API returns 401/404/409/422 with clear messages.

## Running locally

```bash
pip install -r requirements.txt -r requirements-dev.txt
export ECHO_API_KEY=dev-key                      # optional; unset = auth off
uvicorn echo.main:app --reload                   # http://localhost:8000/docs
pytest -q                                         # hermetic SQLite, dry-run
```
