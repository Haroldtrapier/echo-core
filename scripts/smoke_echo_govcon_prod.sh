#!/usr/bin/env bash
#
# Echo GovCon — production smoke suite
# ------------------------------------
# Exercises the full production MVP loop against a running Echo Core deployment:
#   health → db-health → auth gate → live-publish flag → GovCon registry →
#   run govcon_daily_brief → run record → approval draft → approve →
#   draft_approved event → Sturgeon handoff → handoff record → handoff event →
#   weekly_performance_tracker → no-auto-publish.
#
# SAFE FOR PRODUCTION:
#   * Never enables live publishing and asserts live_publishing_enabled=false.
#   * Never publishes/sends external content — it only creates review drafts and
#     an intake handoff (both clearly marked [SMOKE TEST]); approval only flips
#     status + records analytics, it does NOT publish.
#   * Uses smoke payloads only. Note: it DOES write a few rows to the production
#     database (one workflow run + one approval draft + one Sturgeon handoff +
#     analytics events) — that is inherent to an end-to-end smoke test.
#   * If STURGEON_API_URL is configured on the server, the handoff will be
#     forwarded to Sturgeon's intake endpoint; the payload is labelled
#     "[SMOKE TEST]" so it is easy to identify and discard. It never touches
#     billing, Stripe, proposal credits, or human-review logic.
#
# Usage:
#   BASE=https://<echo>.up.railway.app ECHO_API_KEY=*** bash scripts/smoke_echo_govcon_prod.sh
#
# Requires: bash, curl, jq. Exit code 0 = GO (all pass), 1 = NO-GO (a check failed),
# 2 = usage/prereq error.

set -uo pipefail

# ── inputs ────────────────────────────────────────────────────────────────────
BASE="${BASE:-}"
ECHO_API_KEY="${ECHO_API_KEY:-}"

if [[ -z "$BASE" || -z "$ECHO_API_KEY" ]]; then
  echo "ERROR: BASE and ECHO_API_KEY are both required." >&2
  echo "Usage: BASE=https://<echo>.up.railway.app ECHO_API_KEY=*** bash scripts/smoke_echo_govcon_prod.sh" >&2
  exit 2
fi
command -v curl >/dev/null 2>&1 || { echo "ERROR: 'curl' is required." >&2; exit 2; }
command -v jq   >/dev/null 2>&1 || { echo "ERROR: 'jq' is required (https://jqlang.github.io/jq/)." >&2; exit 2; }

BASE="${BASE%/}"  # strip any trailing slash

# The API key lives only inside this array — it is never echoed anywhere.
AUTH=(-H "x-echo-key: ${ECHO_API_KEY}" -H "Content-Type: application/json")

BODY="$(mktemp)"; trap 'rm -f "$BODY"' EXIT
CODE=0
PASS=0; FAIL=0; declare -a RESULTS=()

pass(){ PASS=$((PASS+1)); RESULTS+=("PASS  $1"); echo "  ✅ PASS: $1"; }
fail(){ FAIL=$((FAIL+1)); RESULTS+=("FAIL  $1"); echo "  ❌ FAIL: $1"; }

# call METHOD PATH [DATA] [--noauth]  → body into $BODY, http status into $CODE
call(){
  local method="$1" path="$2" data="${3:-}"; local auth=1
  [[ "${4:-}" == "--noauth" ]] && auth=0
  local hdr=(); if (( auth )); then hdr=("${AUTH[@]}"); else hdr=(-H "Content-Type: application/json"); fi
  if [[ -n "$data" ]]; then
    CODE=$(curl -sS -m 30 -o "$BODY" -w '%{http_code}' -X "$method" "${hdr[@]}" "$BASE$path" -d "$data" 2>/dev/null || echo 000)
  else
    CODE=$(curl -sS -m 30 -o "$BODY" -w '%{http_code}' -X "$method" "${hdr[@]}" "$BASE$path" 2>/dev/null || echo 000)
  fi
}
jqget(){ jq -r "$1" "$BODY" 2>/dev/null; }

echo "Echo GovCon production smoke suite"
echo "BASE=$BASE   (API key hidden)"
echo "──────────────────────────────────────────────"

# init vars used across steps
RUN_ID=""; AID=""; PID=""; HID=""; LPE=""

# 1. health --------------------------------------------------------------------
echo "[1] GET /api/v1/health"
call GET /api/v1/health "" --noauth
if [[ "$CODE" == 200 && "$(jqget .status)" == "ok" ]]; then pass "health returns ok"
else fail "health (HTTP $CODE)"; fi

# 2. db-health -----------------------------------------------------------------
echo "[2] GET /api/v1/db-health"
call GET /api/v1/db-health "" --noauth
if [[ "$CODE" == 200 ]]; then
  echo "     db_url_safe : $(jqget .db_url_safe)"
  echo "     reachable   : $(jqget .db_reachable)"
  echo "     echo_tables : $(jq -c '.echo_tables' "$BODY" 2>/dev/null)"
  if [[ "$(jqget .db_reachable)" == "true" ]]; then pass "db-health reachable"
  else fail "db-health: database not reachable"; fi
else fail "db-health (HTTP $CODE)"; fi

# 3. protected route WITHOUT key → 401 -----------------------------------------
echo "[3] GET /api/v1/workflows  (no key → expect 401)"
CODE=$(curl -sS -m 30 -o /dev/null -w '%{http_code}' -H "Content-Type: application/json" "$BASE/api/v1/workflows" 2>/dev/null || echo 000)
if [[ "$CODE" == 401 ]]; then pass "auth enabled: no key → 401"
else fail "auth: no key expected 401, got $CODE (auth may be DISABLED — NO-GO)"; fi

# 4. protected route WITH key → 200 --------------------------------------------
echo "[4] GET /api/v1/workflows  (with key → expect 200)"
call GET /api/v1/workflows
if [[ "$CODE" == 200 ]]; then pass "auth: valid key → 200"
else fail "auth: valid key expected 200, got $CODE"; fi

# 5. live publishing must be OFF -----------------------------------------------
echo "[5] GET /api/v1/echo/status  (live_publishing_enabled → expect false)"
call GET /api/v1/echo/status
LPE="$(jqget .live_publishing_enabled)"
if [[ "$LPE" == "false" ]]; then pass "live_publishing_enabled=false"
else fail "live_publishing_enabled expected false, got '$LPE' (NO-GO if true)"; fi

# 6. GovCon registry lists 6 workflows -----------------------------------------
echo "[6] GET /api/v1/govcon/workflows/registry?product_area=echo_govcon"
call GET "/api/v1/govcon/workflows/registry?product_area=echo_govcon"
CNT="$(jqget '.count')"
echo "     workflows: $(jq -c '[.workflows[].workflow_id]' "$BODY" 2>/dev/null)"
if [[ "$CODE" == 200 && "$CNT" == "6" ]]; then pass "registry lists 6 Echo GovCon workflows"
else fail "registry expected 6 workflows, got '$CNT' (HTTP $CODE)"; fi

# 7. run govcon_daily_brief ----------------------------------------------------
echo "[7] POST /api/v1/workflows/govcon_daily_brief/run"
call POST /api/v1/workflows/govcon_daily_brief/run '{"payload":{"keywords":["smoke-test"]},"triggered_by":"prod-smoke"}'
RUN_ID="$(jqget .run_id)"; AID="$(jqget .result.approval_id)"; PID="$(jqget .result.post_id)"
if [[ "$CODE" == 200 && "$(jqget .status)" == "succeeded" ]]; then pass "govcon_daily_brief ran (succeeded)"
else fail "govcon_daily_brief run (HTTP $CODE status $(jqget .status))"; fi

# 8. workflow run record -------------------------------------------------------
echo "[8] GET /api/v1/runs/$RUN_ID"
if [[ -n "$RUN_ID" && "$RUN_ID" != "null" ]]; then
  call GET "/api/v1/runs/$RUN_ID"
  if [[ "$CODE" == 200 && "$(jqget .slug)" == "govcon_daily_brief" ]]; then pass "workflow run record persisted"
  else fail "run record missing (HTTP $CODE)"; fi
else fail "no run_id returned from step 7"; fi

# 9. approval draft created ----------------------------------------------------
echo "[9] GET /api/v1/govcon/approvals/$AID"
if [[ -n "$AID" && "$AID" != "null" ]]; then
  call GET "/api/v1/govcon/approvals/$AID"
  if [[ "$CODE" == 200 && "$(jqget .draft_type)" == "brief" ]]; then pass "approval draft created (brief)"
  else fail "approval draft missing (HTTP $CODE type $(jqget .draft_type))"; fi
else fail "no approval_id returned from step 7"; fi

# 10. approve the draft --------------------------------------------------------
echo "[10] POST /api/v1/govcon/approvals/$AID/approve"
if [[ -n "$AID" && "$AID" != "null" ]]; then
  call POST "/api/v1/govcon/approvals/$AID/approve" '{"reviewed_by":"prod-smoke-runner"}'
  if [[ "$CODE" == 200 && "$(jqget .status)" == "approved" ]]; then pass "draft approved"
  else fail "approve failed (HTTP $CODE status $(jqget .status))"; fi
else fail "cannot approve — no approval_id"; fi

# 11. draft_approved analytics event -------------------------------------------
echo "[11] GET /api/v1/govcon/analytics/events?event_type=draft_approved"
call GET "/api/v1/govcon/analytics/events?event_type=draft_approved&limit=200"
if jq -e --arg a "$AID" '.events[]? | select(.metadata.approval_id==$a)' "$BODY" >/dev/null 2>&1; then
  pass "draft_approved analytics event recorded"
else fail "draft_approved event not found for $AID"; fi

# 12. create Sturgeon handoff --------------------------------------------------
echo "[12] POST /api/v1/govcon/sturgeon/handoff"
HANDOFF='{"opportunity_title":"[SMOKE TEST] Echo GovCon production smoke — please ignore","agency":"SMOKE","solicitation_number":"SMOKE-000","due_date":"2099-01-01","summary":"Automated production smoke test record. Not a real opportunity.","recommended_next_action":"No action — delete this smoke record."}'
call POST /api/v1/govcon/sturgeon/handoff "$HANDOFF"
HID="$(jqget .id)"
if [[ "$CODE" == 200 && -n "$HID" && "$HID" != "null" ]]; then pass "Sturgeon handoff created (status=$(jqget .status))"
else fail "Sturgeon handoff create failed (HTTP $CODE)"; fi

# 13. handoff record logged ----------------------------------------------------
echo "[13] GET /api/v1/govcon/sturgeon/handoffs/$HID"
if [[ -n "$HID" && "$HID" != "null" ]]; then
  call GET "/api/v1/govcon/sturgeon/handoffs/$HID"
  if [[ "$CODE" == 200 && "$(jqget .id)" == "$HID" ]]; then pass "handoff record logged"
  else fail "handoff record missing (HTTP $CODE)"; fi
else fail "no handoff id returned from step 12"; fi

# 14. sturgeon_handoff_created analytics event ---------------------------------
echo "[14] GET /api/v1/govcon/analytics/events?event_type=sturgeon_handoff_created"
call GET "/api/v1/govcon/analytics/events?event_type=sturgeon_handoff_created&limit=200"
if jq -e --arg h "$HID" '.events[]? | select(.metadata.handoff_id==$h)' "$BODY" >/dev/null 2>&1; then
  pass "sturgeon_handoff_created analytics event recorded"
else fail "sturgeon_handoff_created event not found for $HID"; fi

# 15. weekly_performance_tracker -----------------------------------------------
echo "[15] POST /api/v1/workflows/weekly_performance_tracker/run"
call POST /api/v1/workflows/weekly_performance_tracker/run '{"payload":{}}'
if [[ "$CODE" == 200 && "$(jqget .status)" == "succeeded" ]]; then pass "weekly_performance_tracker ran (succeeded)"
else fail "weekly_performance_tracker (HTTP $CODE status $(jqget .status))"; fi

# 16. NO auto-publish ----------------------------------------------------------
echo "[16] no-auto-publish check"
call GET "/api/v1/content?published=true"
PUB_TOTAL="$(jqget .total)"
call GET "/api/v1/publishing-jobs?limit=200"
PUB_JOBS="$(jq '[.jobs[]? | select(.status=="published")] | length' "$BODY" 2>/dev/null)"
echo "     content published=$PUB_TOTAL  publishing_jobs_published=${PUB_JOBS:-0}  live_publishing_enabled=$LPE"
if [[ "$PUB_TOTAL" == "0" && "${PUB_JOBS:-0}" == "0" && "$LPE" == "false" ]]; then
  pass "no auto-publish (0 published, live publishing off)"
else fail "auto-publish check (content_published=$PUB_TOTAL jobs_published=${PUB_JOBS:-0} live=$LPE)"; fi

# ── summary ───────────────────────────────────────────────────────────────────
echo
echo "════════════════ SMOKE SUMMARY ════════════════"
printf '  %s\n' "${RESULTS[@]}"
echo "────────────────────────────────────────────────"
echo "  Total: $((PASS+FAIL))   PASS: $PASS   FAIL: $FAIL"
if (( FAIL == 0 )); then
  echo "  RESULT: ✅ GO — all Echo GovCon smoke checks passed"
  exit 0
else
  echo "  RESULT: ❌ NO-GO — $FAIL check(s) failed (see above)"
  exit 1
fi
