# Syncing env vars to Vercel / Railway (`scripts/sync-env.sh`)

The secrets this app needs at runtime are intentionally **not** committed. This
script is the "make it live" step: it reads a local env file and uploads every
variable to the hosting platform(s) this repo deploys to, so the deployed site
actually has its keys.

## 1. Fill in your secrets locally

```bash
cp .env.example .env.production   # then edit .env.production with REAL values
```

`.env.production` is git-ignored — keep it that way. Empty values and comment
lines are skipped, so you only push what you've filled in.

## 2. Authenticate the CLIs (one time)

```bash
# Vercel
npm i -g vercel && vercel login && vercel link      # or: export VERCEL_TOKEN=...

# Railway
npm i -g @railway/cli && railway login && railway link   # or: export RAILWAY_TOKEN=...
```

## 3. Preview, then push

```bash
scripts/sync-env.sh --dry-run     # shows every var + masked length, changes nothing
scripts/sync-env.sh               # actually uploads to the detected platform(s)
```

The platform is auto-detected from the repo (`vercel.json`/`.vercel/` → Vercel,
`railway.json`/`nixpacks.toml` → Railway). Force one with `--vercel` / `--railway`.

## 4. Redeploy to apply

```bash
vercel --prod        # Vercel
railway up           # Railway  (or click "Deploy" in the dashboard)
```

## Options

| Flag | Purpose |
|------|---------|
| `--env-file <path>` | Use a specific file (default: `.env.production`, then `.env.local`, then `.env`). |
| `--vercel` / `--railway` | Force a platform instead of auto-detecting. |
| `--target <envs>` | Vercel targets, comma-separated: `production,preview,development` (default `production,preview`). |
| `--service <name>` | Railway service to target (defaults to the linked service). |
| `--environment <e>` | Railway environment (default `production`). |
| `--dry-run` | Print what would be set (names + masked lengths). No CLI calls, no secrets shown. |
| `--yes` | Don't prompt when overwriting existing Vercel vars. |

The script never prints secret values — only variable names and a character
count, so it's safe to run in shared terminals and CI logs.
