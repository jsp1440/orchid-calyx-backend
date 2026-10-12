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
if [[ "${CALYX_ACCEPTANCE_DATABASE_CONFIRMED:-}" != "non-production" ]]; then
  echo '{"started": false, "zero_reason": "configuration_unavailable", "detail": "CALYX_ACCEPTANCE_DATABASE_CONFIRMED must equal non-production"}'
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
  git -C "$work/brain" -c "http.extraheader=AUTHORIZATION: basic $auth" \
    fetch -q --depth 1 https://github.com/jsp1440/Orchid-Continuum-Brain "$OC_BRAIN_REF"
  git -C "$work/brain" checkout -q FETCH_HEAD
  unset auth
fi

python scripts/oc_autonomy_acceptance_manifest.py \
  --workspace "$work/workspace" --brain-checkout "$work/brain" \
  --output "$work/manifest.json"

python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level warning &
api=$!
for _ in $(seq 1 120); do
  curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1 && break
  sleep 1
done

export CALYX_BACKEND_BASE_URL=http://127.0.0.1:8000
export OC_BRAIN_CHECKOUT="$work/brain"
export OC_BRAIN_WORK_MANIFEST="$work/manifest.json"
export OC_BRAIN_PULSE_LEDGER="$work/brain-ledger.json"
export CALYX_PROGRAM_AUTONOMY_WORKSPACE="$work/workspace"
export GITHUB_REPOSITORY=jsp1440/orchid-calyx-backend

python -m runtime.program_autonomy_brain_worker &
worker=$!
# Render sends SIGTERM on stop/deploy: the worker finishes its cycle and
# settles leases (graceful stop), then the API is stopped.
trap 'kill -TERM "$worker" 2>/dev/null; wait "$worker"; kill -TERM "$api" 2>/dev/null' TERM INT
wait "$worker"
kill -TERM "$api" 2>/dev/null || true
