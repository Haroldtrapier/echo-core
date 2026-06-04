#!/usr/bin/env bash
#
# sync-env.sh — Push local environment variables to Vercel and/or Railway.
#
# This is the "make it live" step: it reads a local env file (the secrets that
# are deliberately NOT committed to the repo) and uploads each variable to the
# hosting platform(s) this project deploys to. Run it once after filling in your
# env file, then redeploy.
#
# It auto-detects platforms from files in the repo root:
#   • Vercel   → vercel.json or a .vercel/ directory
#   • Railway  → railway.json, railway.toml, or nixpacks.toml
# Override detection with --vercel / --railway.
#
# --------------------------------------------------------------------------
# USAGE
#   scripts/sync-env.sh [options]
#
# OPTIONS
#   --env-file <path>   Env file to read (default: first of .env.production,
#                       .env.local, .env that exists).
#   --vercel            Force-enable the Vercel sync.
#   --railway           Force-enable the Railway sync.
#   --target <envs>     Vercel target(s): comma list of production,preview,
#                       development (default: production,preview).
#   --service <name>    Railway service name (optional; uses linked service).
#   --environment <e>   Railway environment name (default: production).
#   --dry-run           Show exactly what WOULD be set, without calling any CLI
#                       or printing secret values. Safe to run anywhere.
#   --yes               Don't prompt before overwriting existing Vercel vars.
#   -h, --help          Show this help.
#
# AUTH (real runs)
#   Vercel : `vercel login` once, OR export VERCEL_TOKEN=...
#            Project must be linked (`vercel link`) or have a .vercel/ dir.
#   Railway: `railway login` once, OR export RAILWAY_TOKEN=...
#            Project must be linked (`railway link`).
#
# The script never echoes secret values; it prints only variable names and a
# masked length. Empty values and comment lines in the env file are skipped.
# --------------------------------------------------------------------------

set -euo pipefail

# ---- defaults --------------------------------------------------------------
ENV_FILE=""
DO_VERCEL=0
DO_RAILWAY=0
FORCED=0
VERCEL_TARGETS="production,preview"
RAILWAY_SERVICE=""
RAILWAY_ENVIRONMENT="production"
DRY_RUN=0
ASSUME_YES=0

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

color()  { printf "\033[%sm%s\033[0m" "$1" "$2"; }
info()   { printf "%s %s\n" "$(color '1;34' '›')" "$*"; }
ok()     { printf "%s %s\n" "$(color '1;32' '✓')" "$*"; }
warn()   { printf "%s %s\n" "$(color '1;33' '!')" "$*" >&2; }
err()    { printf "%s %s\n" "$(color '1;31' '✗')" "$*" >&2; }

usage() { sed -n '2,/^set -euo/p' "$0" | sed 's/^# \{0,1\}//; s/^#$//' | sed '$d'; }

# ---- arg parsing -----------------------------------------------------------
while [ $# -gt 0 ]; do
  case "$1" in
    --env-file)     ENV_FILE="${2:?--env-file needs a path}"; shift 2 ;;
    --vercel)       DO_VERCEL=1; FORCED=1; shift ;;
    --railway)      DO_RAILWAY=1; FORCED=1; shift ;;
    --target)       VERCEL_TARGETS="${2:?--target needs a value}"; shift 2 ;;
    --service)      RAILWAY_SERVICE="${2:?--service needs a value}"; shift 2 ;;
    --environment)  RAILWAY_ENVIRONMENT="${2:?--environment needs a value}"; shift 2 ;;
    --dry-run)      DRY_RUN=1; shift ;;
    --yes|-y)       ASSUME_YES=1; shift ;;
    -h|--help)      usage; exit 0 ;;
    *)              err "Unknown option: $1"; echo; usage; exit 2 ;;
  esac
done

# ---- platform auto-detection ----------------------------------------------
if [ "$FORCED" -eq 0 ]; then
  if [ -f "$ROOT_DIR/vercel.json" ] || [ -d "$ROOT_DIR/.vercel" ]; then DO_VERCEL=1; fi
  if [ -f "$ROOT_DIR/railway.json" ] || [ -f "$ROOT_DIR/railway.toml" ] || [ -f "$ROOT_DIR/nixpacks.toml" ]; then
    DO_RAILWAY=1
  fi
fi

if [ "$DO_VERCEL" -eq 0 ] && [ "$DO_RAILWAY" -eq 0 ]; then
  err "No target platform detected or selected. Use --vercel and/or --railway."
  exit 1
fi

# ---- locate env file -------------------------------------------------------
if [ -z "$ENV_FILE" ]; then
  for cand in "$ROOT_DIR/.env.production" "$ROOT_DIR/.env.local" "$ROOT_DIR/.env"; do
    if [ -f "$cand" ]; then ENV_FILE="$cand"; break; fi
  done
fi
if [ -z "$ENV_FILE" ] || [ ! -f "$ENV_FILE" ]; then
  err "No env file found. Create .env.production (or pass --env-file <path>)."
  err "Tip: copy .env.example and fill in real values."
  exit 1
fi

info "Repo:      $(basename "$ROOT_DIR")"
info "Env file:  ${ENV_FILE#"$ROOT_DIR"/}"
[ "$DO_VERCEL" -eq 1 ]  && info "Vercel:    targets=[$VERCEL_TARGETS]"
[ "$DO_RAILWAY" -eq 1 ] && info "Railway:   environment=$RAILWAY_ENVIRONMENT${RAILWAY_SERVICE:+ service=$RAILWAY_SERVICE}"
[ "$DRY_RUN" -eq 1 ]    && warn "DRY RUN — no changes will be made, no secrets printed."
echo

# ---- parse env file into KEY/VALUE arrays ---------------------------------
# Supports `KEY=value`, optional `export `, quoted values, and inline `# ...`
# only when the value is unquoted. Skips blanks, comments, and empty values.
KEYS=(); VALS=()
line_no=0
while IFS= read -r raw || [ -n "$raw" ]; do
  line_no=$((line_no + 1))
  line="${raw#"${raw%%[![:space:]]*}"}"            # ltrim
  [ -z "$line" ] && continue
  case "$line" in \#*) continue ;; esac
  line="${line#export }"
  case "$line" in *=*) ;; *) warn "skip line $line_no (no '='): $line"; continue ;; esac
  key="${line%%=*}"
  val="${line#*=}"
  key="${key%"${key##*[![:space:]]}"}"             # rtrim key
  key="${key#"${key%%[![:space:]]*}"}"             # ltrim key
  # strip surrounding quotes; otherwise drop trailing inline comment
  case "$val" in
    \"*\") val="${val%\"}"; val="${val#\"}" ;;
    \'*\') val="${val%\'}"; val="${val#\'}" ;;
    *)
      val="${val%%#*}"
      val="${val%"${val##*[![:space:]]}"}"         # rtrim
      ;;
  esac
  case "$key" in
    ""|[0-9]*|*[!A-Za-z0-9_]*) warn "skip line $line_no (bad key): $key"; continue ;;
  esac
  [ -z "$val" ] && continue                        # don't push empty secrets
  KEYS+=("$key"); VALS+=("$val")
done < "$ENV_FILE"

if [ "${#KEYS[@]}" -eq 0 ]; then
  err "No non-empty variables found in $ENV_FILE — nothing to sync."
  exit 1
fi
ok "Parsed ${#KEYS[@]} variable(s) to sync."
echo

mask() { local n=${#1}; printf "<%d char%s>" "$n" "$([ "$n" -eq 1 ] || echo s)"; }

# ---- Vercel ----------------------------------------------------------------
sync_vercel() {
  info "── Vercel ───────────────────────────────────────────"
  if [ "$DRY_RUN" -eq 0 ] && ! command -v vercel >/dev/null 2>&1; then
    err "vercel CLI not found. Install: npm i -g vercel"; return 1
  fi
  local tokflag=(); [ -n "${VERCEL_TOKEN:-}" ] && tokflag=(--token "$VERCEL_TOKEN")
  IFS=',' read -ra targets <<< "$VERCEL_TARGETS"
  local i
  for i in "${!KEYS[@]}"; do
    local k="${KEYS[$i]}" v="${VALS[$i]}"
    for t in "${targets[@]}"; do
      t="$(echo "$t" | tr -d '[:space:]')"; [ -z "$t" ] && continue
      if [ "$DRY_RUN" -eq 1 ]; then
        printf "  would set %-34s [%s] %s\n" "$k" "$t" "$(mask "$v")"
        continue
      fi
      # Remove existing value first so add never fails on conflict.
      if [ "$ASSUME_YES" -eq 1 ]; then
        vercel env rm "$k" "$t" --yes "${tokflag[@]}" >/dev/null 2>&1 || true
      else
        vercel env rm "$k" "$t" "${tokflag[@]}" >/dev/null 2>&1 || true
      fi
      if printf '%s' "$v" | vercel env add "$k" "$t" "${tokflag[@]}" >/dev/null 2>&1; then
        printf "  set %-34s [%s] %s\n" "$k" "$t" "$(mask "$v")"
      else
        err "failed to set $k [$t]"
      fi
    done
  done
  ok "Vercel sync complete."
  [ "$DRY_RUN" -eq 0 ] && info "Redeploy to apply: vercel --prod"
  echo
}

# ---- Railway ---------------------------------------------------------------
sync_railway() {
  info "── Railway ──────────────────────────────────────────"
  if [ "$DRY_RUN" -eq 0 ] && ! command -v railway >/dev/null 2>&1; then
    err "railway CLI not found. Install: npm i -g @railway/cli"; return 1
  fi
  local base=(railway variables)
  [ -n "$RAILWAY_SERVICE" ]     && base+=(--service "$RAILWAY_SERVICE")
  [ -n "$RAILWAY_ENVIRONMENT" ] && base+=(--environment "$RAILWAY_ENVIRONMENT")
  local i
  for i in "${!KEYS[@]}"; do
    local k="${KEYS[$i]}" v="${VALS[$i]}"
    if [ "$DRY_RUN" -eq 1 ]; then
      printf "  would set %-34s %s\n" "$k" "$(mask "$v")"
      continue
    fi
    # --skip-deploys batches changes; we trigger one redeploy at the end.
    if "${base[@]}" --set "$k=$v" --skip-deploys >/dev/null 2>&1; then
      printf "  set %-34s %s\n" "$k" "$(mask "$v")"
    else
      err "failed to set $k"
    fi
  done
  ok "Railway sync complete."
  [ "$DRY_RUN" -eq 0 ] && info "Redeploy to apply: railway up   (or trigger from the dashboard)"
  echo
}

[ "$DO_VERCEL" -eq 1 ]  && sync_vercel
[ "$DO_RAILWAY" -eq 1 ] && sync_railway

ok "Done."
