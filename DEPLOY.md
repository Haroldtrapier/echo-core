# Echo Core — Go-Live Runbook

Turnkey deployment of Echo Core (GovCon automation backend) on **Railway** +
**Supabase**, with the **cockpit** on any static host. Follow top to bottom; the
whole thing takes ~30–45 minutes.

Echo ships **dry-run by default** — no post, DM, or email leaves the building
until you explicitly flip `ECHO_ALLOW_LIVE_PUBLISH=true` in Step 7. Deploy with
confidence and review dry-run output first.

---

## 0. Prerequisites

- A Railway account + the Railway CLI (optional) — https://railway.app
- A Supabase project (provides Postgres) — https://supabase.com
- A strong `ECHO_API_KEY` secret. Generate one:
  ```bash
  python -c "import secrets; print(secrets.token_urlsafe(32))"
  ```

---

## 1. Database — run the Supabase migrations

In the Supabase dashboard → **SQL Editor**, run each file in order (all are
idempotent and safe to re-run):

1. `supabase/migrations/0001_echo_core_schema.sql` — `workflow_runs`, `approvals`
2. `supabase/migrations/0002_cockpit_read_models.sql` — `content_items`, `publishing_jobs`, `automation_logs`, `integration_health`
3. `supabase/migrations/0003_echo_jobs.sql` — `echo_jobs`, `echo_job_schedules`, `echo_execution_audits`
4. `supabase/migrations/0004_echo_govcon.sql` — `echo_workflows`, `echo_analytics_events`, `echo_sturgeon_handoffs`, compatibility views
5. `supabase/migrations/0005_id_type_reconciliation.sql` — align id columns (`UUID`→`TEXT`) with the ORM

> The app also calls `create_tables()` on startup, so tables self-heal — but
> running the migrations first gives you the exact, reviewed schema.

Grab the connection string: Supabase → **Project Settings → Database →
Connection string (URI)**. Use the **pooler** URI for serverless. It looks like:
```
postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres
```

---

## 2. Required environment variables

Set these on **both** Railway services (Web + Worker) in Step 3–4.

| Variable | Value |
|---|---|
| `DATABASE_URL` | the Supabase pooler URI from Step 1 |
| `ECHO_API_KEY` | the secret you generated in Step 0 |

Leave everything else default for the first deploy (dry-run, all integrations
"feature disabled"). You will add integration keys in Step 6.

---

## 3. Deploy **Echo Web** (the API)

1. Railway → **New Project → Deploy from GitHub repo** → select `echo-core`.
2. Railway auto-detects `railway.json`:
   - start: `uvicorn echo.main:app --host 0.0.0.0 --port $PORT`
   - healthcheck: `/api/v1/health`
3. Add the two required env vars from Step 2.
4. Deploy. When the healthcheck is green, grab the public URL, e.g.
   `https://echo-core-production.up.railway.app`.

**Smoke-check** (replace host + key):
```bash
HOST=https://echo-core-production.up.railway.app
KEY=your_echo_api_key

# Unauthenticated health (should be {"status":"ok",...})
curl -s $HOST/api/v1/health

# DB connectivity + which echo_ tables exist
curl -s $HOST/api/v1/db-health

# Auth works → lists 9 workflows
curl -s -H "x-echo-key: $KEY" $HOST/api/v1/workflows | python -m json.tool

# Missing key → 401
curl -s -o /dev/null -w "%{http_code}\n" $HOST/api/v1/workflows
```

---

## 4. Deploy **Echo Worker** (the scheduler)

1. In the same Railway project → **New Service → from the same repo**.
2. Override the start command:
   ```
   python -m echo.worker
   ```
3. Give it the **same** `DATABASE_URL` + `ECHO_API_KEY` (no separate Postgres).
4. Optional: `WORKER_TICK_INTERVAL` (seconds, default `60`),
   `ECHO_ENABLED=false` to pause scheduling without removing the service.

---

## 5. Deploy the **Cockpit** (Imani/Apex OS control surface)

The cockpit is a standalone static page (`cockpit/index.html`) — no build step.

- **Quick**: host the `cockpit/` folder on Vercel/Netlify/GitHub Pages, or serve
  it anywhere. Open it, enter your API base URL + `x-echo-key`, click Connect.
- **CORS**: set `CORS_ORIGINS` on the Web service to the cockpit's origin, e.g.
  `https://cockpit.yourdomain.com` (default `*` works but is permissive).
- **Security**: the key is held client-side. For production, front the cockpit
  with a small backend-for-frontend that injects the key and adds auth — don't
  publish a production key in a public static page.

---

## 6. Wire integrations (optional — each is independent)

Add any subset; absent keys leave that integration safely disabled.

| Capability | Env vars | Where to get them |
|---|---|---|
| AI generation (Claude) | `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` | https://console.anthropic.com |
| SAM.gov opportunities | `SAM_GOV_API_KEY` | https://sam.gov/profile/details |
| LinkedIn publishing | `LINKEDIN_ACCESS_TOKEN`, `LINKEDIN_AUTHOR_URN` | LinkedIn developer app (`w_member_social`) |
| Buffer scheduling | `BUFFER_API_KEY`, `BUFFER_PROFILE_IDS` | https://buffer.com/developers/apps |
| Slack alerts | `SLACK_WEBHOOK_URL` | https://api.slack.com/messaging/webhooks |
| GA4 attribution | `GA4_PROPERTY_ID`, `GA4_ACCESS_TOKEN` | GA4 Admin → property id; see GA4 note below |
| Instagram image (auto) | `IMAGE_API_KEY` (+ image hosting below) | OpenAI-compatible images API |
| TikTok video (auto) | `VIDEO_API_KEY`, `VIDEO_API_URL` | your render service (contract below) |
| Image hosting | `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `MEDIA_BUCKET` | Supabase → Storage |

**GA4 token note.** The Data API needs an OAuth2 bearer token. Create a Google
**service account**, grant it **Viewer** on the GA4 property, and run a small
refresher (Cloud Function / cron) that mints an access token and writes it to
`GA4_ACCESS_TOKEN`. Until then GA4 reports `ga4_configured: false` and the
Weekly Report falls back to DB inventory.

### Instagram image hosting

Instagram requires a real, publicly-fetchable image URL (Buffer can't post
base64). The flow:

1. Set `IMAGE_API_KEY` (OpenAI-compatible images API). Models like `gpt-image-1`
   return **base64**, not a URL.
2. Create a **public** Supabase Storage bucket (default name `echo-media`), then
   set `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, and `MEDIA_BUCKET`. Echo uploads
   the generated image and uses the resulting public URL.
3. Generate with `social_post` (`"auto_media": true`) or attach later with
   `produce_media` (`{"post_id": "..."}`).

If the image API returns a hosted URL directly (e.g. some DALL·E configs), the
storage step is optional. Without hosting **and** with a base64-only model, the
draft stays `needs_media` (it will not publish without a usable image).

### TikTok render-service contract (`VIDEO_API_URL`)

Echo generates the **script** and delegates rendering to your service. Point
`VIDEO_API_URL` at an endpoint that:

- **Receives** `POST` with `Authorization: Bearer $VIDEO_API_KEY` and JSON body:
  ```json
  { "script": "<the TikTok script Echo generated>", "voice": "default" }
  ```
- **Returns** JSON containing the finished asset URL:
  ```json
  { "video_url": "https://cdn.example/echo/clip.mp4" }
  ```
  (An async service may instead return `{ "job_id": "..." }`; Echo then reports
  `needs_production` until you attach the finished URL via `produce_media` or by
  re-running once the URL is known.)

Until a render service is wired, TikTok drafts stay `needs_media` — Echo never
fabricates video.

---

## 7. Go live (flip the publish gate)

Until now every publish has been a labeled dry-run. Validate, then enable:

```bash
# 1. Generate a draft (queues a ContentItem, returns post_id)
curl -s -H "x-echo-key: $KEY" -H "Content-Type: application/json" \
  -d '{"payload":{"topic":"CMMC 2.0 readiness for small contractors"}}' \
  $HOST/api/v1/workflows/linkedin_signal_post/run | python -m json.tool

# 2. See it in the Content Queue
curl -s -H "x-echo-key: $KEY" "$HOST/api/v1/content?status=pending_review"

# 3. Request approval (returns approval_id), then approve it
curl -s -H "x-echo-key: $KEY" -H "Content-Type: application/json" \
  -d '{"payload":{"platform":"linkedin","post_id":"POST_ID"}}' \
  $HOST/api/v1/workflows/approved_publisher/run

curl -s -H "x-echo-key: $KEY" -H "Content-Type: application/json" \
  -d '{"decision":"approved","decision_by":"you"}' \
  $HOST/api/v1/approvals/APPROVAL_ID/decide
```

When the dry-run output looks right, set on the **Web + Worker** services:
```
ECHO_ALLOW_LIVE_PUBLISH=true
```
Now re-running `approved_publisher` with the `approval_id` performs a real
publish (LinkedIn immediate, or Buffer with `scheduled_at`).

> Roll back instantly by setting `ECHO_ALLOW_LIVE_PUBLISH=false` (or unsetting
> it) — the gate defaults to dry-run.

---

## 8. Connect Imani / Apex OS

Trigger workflows from any client with the API key (see `INTEGRATION.md` for
full payloads):

```http
POST /api/v1/workflows/linkedin_signal_post/run
x-echo-key: <ECHO_API_KEY>
Content-Type: application/json

{ "payload": { "topic": "...", "brand": "Sturgeon GovCon" }, "triggered_by": "imani" }
```

Dashboard views map to: `/content`, `/publishing-jobs`, `/approvals`, `/logs`,
`/analytics/summary`.

---

## Operations cheat-sheet

| Need | Action |
|---|---|
| Pause all automation | `ECHO_ENABLED=false` on the Worker |
| Stop all live posting | `ECHO_ALLOW_LIVE_PUBLISH=false` (default) |
| Check DB health | `GET /api/v1/db-health` |
| Pre-deploy validation | `python verify_golive.py` (imports + 9 workflows + DB) |
| Interactive API docs | `GET /docs` |
| Rotate the API key | change `ECHO_API_KEY` on both services + clients |

## Troubleshooting

- **401 on every call** → `ECHO_API_KEY` mismatch between service and client header.
- **DB errors at startup** → check `DATABASE_URL` (use the pooler URI); `/api/v1/db-health` shows the masked URL + reachability.
- **Workflow run returns `status: failed`** with an external 403/timeout → that integration's API key is missing or the host is unreachable; the run is recorded, not crashed.
- **Cockpit can't load** → CORS; set `CORS_ORIGINS` to the cockpit origin.
- **GA4 shows `ga4_configured: false`** → `GA4_PROPERTY_ID`/`GA4_ACCESS_TOKEN` unset or the token expired (see Step 6).
