# Echo Cockpit

A standalone, build-free dashboard for the Echo Core API — the Imani/Apex OS
control surface for GovCon automation. Pure HTML/JS (no framework, no bundler),
so it runs from a file, any static host, Vercel, or GitHub Pages.

It is intentionally **decoupled** from the backend (the Echo Core service has no
frontend dependency). The cockpit talks to the API over HTTP using your
`ECHO_API_KEY`.

## Use

1. Open `index.html` (double-click, or serve it):
   ```bash
   cd cockpit && python -m http.server 5173
   # then visit http://localhost:5173
   ```
2. Enter your **API base** (e.g. `https://your-echo.up.railway.app`) and
   **x-echo-key**, then **Connect**. Both are saved to `localStorage`.

## What it shows

- **Summary cards** — workflow runs, content, publishing jobs, errors, GA4 status (`/analytics/summary`).
- **Workflows** — list all 9, run any with a JSON payload (`/workflows/{slug}/run`).
- **Content Queue** — drafts → approved → published (`/content`).
- **Approvals** — pending items with one-click Approve / Reject (`/approvals`, `/approvals/{id}/decide`).
- **Publishing Jobs** — platform, status, scheduling mode, live URL (`/publishing-jobs`).
- **Logs** — automation log feed (`/logs`).

## Notes

- The API key is held client-side only. For a hardened deployment, front the
  cockpit with a small backend-for-frontend that injects the key server-side and
  add auth in front of it; do not ship a production key in a public static page.
- CORS: set `CORS_ORIGINS` on the backend to the cockpit's origin (default `*`).
