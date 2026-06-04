# Echo Core Integration Guide

## Triggering Workflows from Imani (or Any Client)

### Authentication

```http
POST /api/v1/workflows/linkedin_signal_post/run
x-echo-key: your_echo_api_key
Content-Type: application/json

{
  "payload": {
    "topic": "Federal IT modernization opportunities in Q4",
    "brand": "Apex GovCon"
  },
  "triggered_by": "imani_dashboard"
}
```

### Response

```json
{
  "run_id": "550e8400-e29b-41d4-a716-446655440000",
  "slug": "linkedin_signal_post",
  "status": "succeeded",
  "result": {
    "post_text": "...",
    "dry_run": true,
    "simulated_output": { ... }
  },
  "started_at": "2025-01-15T10:00:00Z",
  "finished_at": "2025-01-15T10:00:03Z"
}
```

---

## Workflow Payloads

### `linkedin_signal_post`
Generates the post and **queues it as a draft** (`status: pending_review`) in the
Content Queue with a UTM-tagged CTA. It does not publish — `approved_publisher`
does, after approval. Returns a `post_id` to reference later.
```json
{
  "topic": "string (required) — the post topic",
  "brand": "string (optional) — brand context",
  "campaign": "string (optional) — UTM campaign (default: govcon_signal)",
  "cta_url": "string (optional) — CTA base URL (default: govconcommandcenter.com)",
  "cta_text": "string (optional)"
}
```

### `social_post`
Generates network-appropriate copy for **linkedin / facebook / instagram /
tiktok** and queues an approval-first draft (returns `post_id`).
- **Instagram** requires an `image_url`; without one the draft is `needs_media`
  and `approved_publisher` refuses a live post.
- **TikTok** produces a *script* and requires a produced video (`image_url` =
  video URL) before a live post. Echo does not generate video.
- Facebook/Instagram/TikTok publish via **Buffer** (connect the channel, target
  it with `BUFFER_PROFILE_IDS`). LinkedIn can publish natively.
```json
{
  "platform": "instagram",
  "topic": "SDVOSB set-aside wins this quarter",
  "brand": "Sturgeon GovCon",
  "image_url": "https://cdn.example/post.jpg",
  "campaign": "q3_wins"
}
```

### `govcon_daily_intelligence`
```json
{
  "keywords": ["cybersecurity", "cloud"],
  "days_back": 7,
  "sam_limit": 5,
  "awards_limit": 5
}
```

### `sam_opportunity_watch`
```json
{
  "keywords": "information technology",
  "limit": 10,
  "days_back": 7,
  "naics_code": "541512",
  "set_aside": "SBA"
}
```

### `fema_disaster_monitor`
```json
{
  "state": "TX",
  "days_back": 14,
  "disaster_type": "DR",
  "limit": 10
}
```

### `weekly_report`
No required payload. Generates from live database state.

### `approved_publisher`
Provide either an inline `content` dict **or** a `post_id` from a draft created by
`linkedin_signal_post` (preferred — it links the publish back to the Content
Queue row and records a Publishing Job). On publish it writes a `publishing_jobs`
row and advances the content item (`approved` → `published` only on a live
publish; dry-runs stop at `approved`).
```json
{
  "platform": "linkedin",
  "post_id": "post_xxxxxxxxxxxx",
  "requested_by": "harold@company.com",
  "scheduled_at": "2030-01-01T09:00:00Z"
}
```
- `platform`: `linkedin` (immediate) or `buffer` (immediate or scheduled).
- `scheduled_at` (optional, Buffer): ISO8601 time — Buffer holds the post until
  then; the content item is marked `scheduled` rather than `published`.
- The linked draft's UTM-tagged CTA (`cta_url`) is automatically included.

Re-run with `approval_id` (and the same `post_id`) after approving via
`POST /approvals/{id}/decide`.

### `content_calendar_archive`
```json
{
  "retention_days": 90,
  "dry_run": true
}
```

---

## Approval Workflow

1. Trigger `approved_publisher` — creates a pending approval, returns `approval_id`
2. Call `GET /api/v1/approvals` to see pending items
3. Call `POST /api/v1/approvals/{id}/decide` with `{"decision": "approved", "decision_by": "harold"}`
4. Re-trigger `approved_publisher` with `approval_id` in the payload — publishes (or dry-run)

---

## Connecting the Cockpit Dashboard

The four cockpit endpoints power the Imani dashboard's Echo section:

| Dashboard View | Echo Endpoint |
|----------------|---------------|
| Content library | `GET /api/v1/content?status=published` |
| Publishing queue | `GET /api/v1/publishing-jobs?status=pending` |
| Error log | `GET /api/v1/logs?level=error` |
| Integration status | `GET /api/v1/integration-health` |
| Summary cards | `GET /api/v1/analytics/summary` |

---

## Environment Variables for Each Integration

### SAM.gov
- `SAM_GOV_API_KEY` — get at https://sam.gov/profile/details

### LinkedIn
- `LINKEDIN_ACCESS_TOKEN` — OAuth 2.0 access token with `w_member_social` scope
- `LINKEDIN_AUTHOR_URN` — your LinkedIn person or organization URN

### Buffer
- `BUFFER_API_KEY` — get at https://buffer.com/developers/apps

### Slack
- `SLACK_WEBHOOK_URL` — incoming webhook URL from https://api.slack.com/messaging/webhooks

### GovCon CMS (if applicable)
- `GOVCON_CMS_URL` — base URL of the CMS instance
- `GOVCON_CMS_API_KEY` — CMS API authentication key

### AI Generation
- `ANTHROPIC_API_KEY` — get at https://console.anthropic.com
- `ANTHROPIC_MODEL` — default: `claude-3-5-haiku-20241022`

---

## Live Publishing Gate

By default, all publish calls are dry-run simulations. No post will be sent to any platform until:

```
ECHO_ALLOW_LIVE_PUBLISH=true
```

is explicitly set in Railway environment variables. This is intentional — review dry-run outputs before enabling.
