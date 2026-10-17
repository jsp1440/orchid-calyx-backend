#!/usr/bin/env bash
# Hosted, non-production autonomy acceptance: one Render background worker.
#
# Runs the real Calyx API on loopback and the deployable Brain worker
# (runtime.program_autonomy_brain_worker) in the same container, against the
# acceptance-only DATABASE_URL. Executors read a fresh read-only branch clone of
# this public repository; Brain is cloned at a pinned SHA with a read-only
# token passed as an HTTP header (never in a URL or log). No provider, no
# production service, no production database.
set -euo pipefail

: "${DATABASE_URL:?acceptance-only DATABASE_URL required}"
: "${CALYX_API_KEY:?CALYX_API_KEY required}"
if [[ -z "${OC_ACCEPTANCE_BRAIN_DIR:-}" ]]; then
  : "${OC_BRAIN_READ_TOKEN:?read-only Brain token required}"
fi
: "${OC_BRAIN_REF:?pinned Brain commit required}"
: "${CALYX_ACCEPTANCE_SOURCE_BRANCH:?branch to verify required}"
# "non-production", or "non-production:<database>" to also pin the database
# name. "autonomy-isolated:<database>" is the long-running worker's form: the
# name is mandatory and must be a dedicated autonomy_* database, so it can never
# name the production application database (neondb) or a shared default. A
# pinned name is checked against the connection the app itself will use before
# anything (API startup included) can write to it.
confirmed="${CALYX_ACCEPTANCE_DATABASE_CONFIRMED:-}"
expected_database=""
case "$confirmed" in
  non-production) ;;
  non-production:?*) expected_database="${confirmed#non-production:}" ;;
  autonomy-isolated:?*)
    expected_database="${confirmed#autonomy-isolated:}"
    if [[ ! "$expected_database" =~ ^autonomy_[a-z0-9_]+$ ]]; then
      echo '{"started": false, "zero_reason": "configuration_unavailable", "detail": "ISOLATED_DATABASE_NAME_REFUSED: autonomy-isolated requires a dedicated autonomy_* database name; worker not started"}'
      exit 0
    fi
    ;;
  *)
    echo '{"started": false, "zero_reason": "configuration_unavailable", "detail": "CALYX_ACCEPTANCE_DATABASE_CONFIRMED must equal non-production, non-production:<database> or autonomy-isolated:<database>"}'
    exit 0
    ;;
esac
if [[ -n "$expected_database" ]]; then
  actual_database="$(python - <<'PY'
from sqlalchemy import text

from app.database import get_engine

with get_engine().connect() as connection:
    print(connection.execute(text("SELECT current_database()")).scalar_one())
PY
)" || {
    echo '{"started": false, "zero_reason": "configuration_unavailable", "detail": "ACCEPTANCE_DATABASE_UNREACHABLE: could not read current_database(); worker not started"}'
    exit 1
  }
  actual_database="$(printf '%s' "$actual_database" | tail -n 1)"
  if [[ "$actual_database" != "$expected_database" ]]; then
    printf '{"started": false, "zero_reason": "configuration_unavailable", "detail": "ACCEPTANCE_DATABASE_MISMATCH: connected to %s, expected %s; worker not started"}\n' \
      "$actual_database" "$expected_database"
    exit 0
  fi
  printf '{"acceptance_database": "%s", "confirmed": true}\n' "$actual_database"
fi

mode="${CALYX_ACCEPTANCE_WORK_MODE:-manifest}"
if [[ "$mode" != manifest && "$mode" != loop ]]; then
  echo '{"started": false, "zero_reason": "configuration_unavailable", "detail": "CALYX_ACCEPTANCE_WORK_MODE must be manifest or loop"}'
  exit 0
fi

work="${TMPDIR:-/tmp}/oc-autonomy-acceptance"
rm -rf "$work" && mkdir -p "$work"

git clone -q --depth 1 --branch "$CALYX_ACCEPTANCE_SOURCE_BRANCH" \
  https://github.com/jsp1440/orchid-calyx-backend "$work/workspace"
git -C "$work/workspace" checkout -q -b autonomy/hosted-acceptance
cat > "$work/workspace/.calyx-isolated-workspace.json" <<JSON
{"schema": "calyx-isolated-workspace-v1", "repository": "jsp1440/orchid-calyx-backend",
 "branch": "autonomy/hosted-acceptance", "disposable": true, "workspace_write_authorized": true}
JSON

if [[ -n "${OC_ACCEPTANCE_BRAIN_DIR:-}" ]]; then
  # Local rehearsal only: an existing Brain checkout at the pinned commit.
  git clone -q "$OC_ACCEPTANCE_BRAIN_DIR" "$work/brain"
  git -C "$work/brain" checkout -q "$OC_BRAIN_REF"
else
  auth="$(printf 'x-access-token:%s' "$OC_BRAIN_READ_TOKEN" | base64 | tr -d '\n')"
  git init -q "$work/brain"
  if ! git -C "$work/brain" -c "http.extraheader=AUTHORIZATION: basic $auth" \
    fetch -q --depth 1 https://github.com/jsp1440/Orchid-Continuum-Brain "$OC_BRAIN_REF"; then
    # A fine-grained token not granted the Brain repository gets 403/404 here.
    echo '{"started": false, "zero_reason": "configuration_unavailable", "detail": "OC_BRAIN_READ_TOKEN cannot fetch jsp1440/Orchid-Continuum-Brain at OC_BRAIN_REF; grant the token that repository (Contents: Read-only)"}'
    exit 1
  fi
  git -C "$work/brain" checkout -q FETCH_HEAD
  unset auth
fi

# Work supply: "manifest" (default) is the finite acceptance manifest; "loop"
# is the continuous Brain autonomy loop. It discovers committed scientific
# batches and changed sources from the refreshed workspace, turns failures and
# recurring defects into gated repair proposals, and records governed
# engineering objectives as proposals.
case "$mode" in
  manifest)
    python scripts/oc_autonomy_acceptance_manifest.py \
      --workspace "$work/workspace" --brain-checkout "$work/brain" \
      --output "$work/manifest.json"
    ;;
  loop)
    if [[ ! -f "$work/brain/calyx_brain/autonomy_loop.py" ]]; then
      echo '{"started": false, "zero_reason": "configuration_unavailable", "detail": "OC_BRAIN_REF has no calyx_brain/autonomy_loop.py; loop mode needs a Brain ref with the autonomy loop"}'
      exit 0
    fi
    ;;
esac

python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level warning &
api=$!
# Never start the worker against an API that is not up: its submissions would
# fail, exhaust their retries and dependency-fail the whole manifest. A small
# instance can take minutes to import the app on a cold start.
healthy=false
for _ in $(seq 1 "${CALYX_ACCEPTANCE_API_WAIT_SECONDS:-600}"); do
  if curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then healthy=true; break; fi
  kill -0 "$api" 2>/dev/null || break
  sleep 1
done
if [[ "$healthy" != true ]]; then
  echo '{"started": false, "zero_reason": "configuration_unavailable", "detail": "CALYX_API_NOT_HEALTHY: the loopback Calyx API never answered /health; worker not started"}'
  kill -TERM "$api" 2>/dev/null || true
  exit 1
fi
echo '{"api": "healthy", "worker": "starting"}'

export CALYX_BACKEND_BASE_URL=http://127.0.0.1:8000
export OC_BRAIN_CHECKOUT="$work/brain"
if [[ "$mode" == loop ]]; then
  queue="$work/brain/14_ENGINEERING/autonomy_mission_queue_v1.json"
  default_observers="scientific_batches,repository_changes:app/traitbank/*.py,completion_feedback,calyx_health,module_signals"
  if [[ -f "$queue" ]]; then
    default_observers="$default_observers,engineering_objectives:$queue"
  fi
  export OC_BRAIN_LOOP_OBSERVERS="${OC_BRAIN_LOOP_OBSERVERS:-$default_observers}"
  # Durable ledger in the acceptance database: survives restarts.
  export OC_BRAIN_PULSE_LEDGER="${OC_BRAIN_PULSE_LEDGER:-database:acceptance-loop}"
  # Follow the source branch so newly committed inputs are discovered.
  export OC_BRAIN_WORKSPACE_REFRESH_SECONDS="${OC_BRAIN_WORKSPACE_REFRESH_SECONDS:-300}"
  export OC_BRAIN_WORKSPACE_REFRESH_REF="${OC_BRAIN_WORKSPACE_REFRESH_REF:-$CALYX_ACCEPTANCE_SOURCE_BRANCH}"
  echo "{\"work_mode\": \"loop\", \"observers\": \"$OC_BRAIN_LOOP_OBSERVERS\"}"
else
  export OC_BRAIN_WORK_MANIFEST="$work/manifest.json"
  export OC_BRAIN_PULSE_LEDGER="$work/brain-ledger.json"
fi
export CALYX_PROGRAM_AUTONOMY_WORKSPACE="$work/workspace"
export GITHUB_REPOSITORY=jsp1440/orchid-calyx-backend

python -m runtime.program_autonomy_brain_worker &
worker=$!
# Render sends SIGTERM on stop/deploy: the worker finishes its cycle and
# settles leases (graceful stop), then the API is stopped.
trap 'kill -TERM "$worker" 2>/dev/null; wait "$worker"; kill -TERM "$api" 2>/dev/null' TERM INT
wait "$worker"
kill -TERM "$api" 2>/dev/null || true
