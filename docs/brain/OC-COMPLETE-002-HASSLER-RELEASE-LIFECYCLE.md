# OC-COMPLETE-002 — exact Hassler release lifecycle and staging readiness exposure

Date: 2026-08-22
Issue: #1084
Parent portfolio: `jsp1440/Orchid-Continuum-Brain#96`
Converges: #386, #264, current Hassler intake code
Lane: 2 (taxonomy and occurrence pipelines)

## Classification

`CONTINUE`. No second taxonomy pipeline was built. This slice adds a
classification and exposure layer over the existing intake lifecycle
(`runtime/world_plants_staging.py`, `runtime/world_plants_durable_intake.py`,
`runtime/world_plants_readiness_api.py`, `runtime/world_plants_activation_decision.py`,
`scripts/upload_hassler_release_guarded.py`). No existing pipeline stage was
duplicated, replaced, or weakened.

## Exact release under governance

| Field | Value |
| --- | --- |
| filename | `WorldOrchids 26-08 (Aug 2 2026).csv` |
| sha256 | `e5be9268e1a48cb0e1777137ac386a9a870f3581c35f10678c9b810c59688c6f` |
| size_bytes | `11529836` |
| version_label | `26-08` |
| acquired_at | `2026-08-02` |

## Prior durable receipt

The Aug 8 2026 receipt (`docs/brain/CALYX-CORE-HASSLER-DURABLE-INTAKE.md`)
recorded, from live read-only discovery against the deployed backend:
`ready_for_upload=true`, `release_count=0`, exact release present `false`,
upload invoked `false`, staging invoked `false`.

**This session could not re-audit that live production state.** See the owner
gate below. The Aug 8 receipt therefore remains the most recent live evidence,
and this document does not assert that it still holds.

## What this slice adds

### 1. Single-answer lifecycle classification

`runtime/hassler_release_lifecycle.py` classifies the exact release into exactly
one state from read-only evidence:

`UNAVAILABLE` · `ABSENT` · `UPLOADED_INSPECTED` · `SMOKE_VERIFIED` ·
`STAGING_IN_PROGRESS` · `STAGED_COMPLETE` · `SUPERSEDED` · `ACTIVATED`

Three invariants are enforced and pinned by tests:

1. **Unavailable is never zero.** A probe that could not be executed produces
   `UNAVAILABLE` plus an `unavailable_evidence` entry. It never collapses into
   `ABSENT`, `0`, or `false`. A release list that returns HTTP 503 does not mean
   the release is absent; a staging query that fails does not mean zero rows are
   staged; a missing smoke gate does not mean the smoke gate failed.
2. **Upload and staging never imply activation.** Migration 107 defines no
   `activated` release state at all. Activation can only be reported from an
   explicit canonical-taxonomy probe. No such probe exists today, so the default
   activation evidence is `unavailable` — not "not activated". Every lifecycle
   payload carries `activation_implied_by_upload_or_staging: false`.
3. **Identity is verified, not assumed.** A missing identity field yields
   `identity_evidence_incomplete`; a contradicted field yields
   `identity_conflict`. The two are never merged.

Supersession is derived only from durable releases acquired strictly after
`2026-08-02`; an older release never supersedes. A completed staging checkpoint
whose staged row count is short of the inspected source row count is reported as
`STAGING_IN_PROGRESS`, not `STAGED_COMPLETE`.

### 2. Mission Control exposure

`GET /api/mission-control/taxonomy/hassler-release-status` (owner-gated,
read-only) returns the lifecycle payload, the downstream relink enumeration, and
a compact `status_block` carrying release identity, `active_release_id`,
`staged_release_id`, `active_vs_staged`, `resumable_from_row_index`,
`open_review_items`, `change_report_present`, and the unavailable-probe list.

`active_vs_staged` distinguishes four outcomes that are frequently conflated:
`unavailable`, `no_active_canonical_release`, `exact_release_is_active`, and
`active_release_differs_from_exact_release`.

### 3. Downstream relink/backfill enumeration

`enumerate_downstream_relink_impact` enumerates all six required surfaces —
occurrences, media, traits, literature, interactions, knowledge_graph — mapped
onto the existing `runtime/world_plants_impact.py` domains. Per-surface record
counts are reported only when a read-only count probe supplies them; otherwise
`count_evidence: "unavailable"` and `affected_records: null`. Counts are never
rendered as zero by default. Malformed rows and duplicate identities surface as
`unresolved_blockers`, and their absence of evidence surfaces as
`*_unavailable` rather than as a clean result.

### 4. Owner-exception receipt instead of assumed incorporation

`build_owner_exception_receipt` records the exact prepared action, its guards,
the blocking reason, the next executable action, and the responsible party,
with `action_executed: false`, `upload_invoked: false`, `staging_invoked: false`
and `incorporation_assumed: false`. The read-only discovery probe emits one
automatically whenever the release is `ABSENT` or `UNAVAILABLE`.

### 5. Extended read-only discovery

`scripts/discover_hassler_release_intake.py` (schema 1.2) now additionally
probes the exact release readback and its durable staging state, and emits
`lifecycle`, `downstream_relink_impact`, `status_block`, and where applicable
`owner_exception_receipt`. Every state read remains a GET; the only POST is the
owner session token, and that is asserted by test.

## Governance boundary

This build performs no upload of the real Hassler release, no staging write, no
taxonomy activation, no canonical species change, no scientific publication, and
no Knowledge Graph mutation. Taxonomy activation remains a separately protected
owner gate and is never implied by upload or staging.

## Validation

Executed on this branch (Python 3.12, local runner):

- `python3 -m pytest tests/test_hassler_release_lifecycle.py` — 28 passed
- `python3 -m pytest tests/test_hassler_release_status_route.py` — 8 passed
- `python3 -m pytest tests/test_hassler_intake_discovery_probe.py` — 3 passed
- Existing taxonomy intake regressions (`test_world_plants_upload_001`,
  `test_world_plants_activation_decision`, `test_world_plants_migration_preflight`,
  `test_upload_hassler_release_guarded`,
  `test_upload_hassler_release_guarded_failure_receipts`,
  `test_calyx_taxonomy_release_intake_461`) — 63 passed, 3 skipped combined with
  the new suites
- `python3 -m ruff check` and `python3 -m ruff format --check` on all changed
  files — clean
- `git diff --check` — clean

These are fixture and contract tests. They are **not** live production evidence.

### CI workflow could not be committed

The coding-agent GitHub App token for this lane lacks the `workflows`
permission. The push was rejected with:

> refusing to allow a GitHub App to create or update workflow
> `.github/workflows/calyx-hassler-intake-discovery.yml` without `workflows`
> permission

The intended validation workflow — running the same compile, lint, format,
new-suite and regression steps above — is therefore preserved verbatim at
`docs/ci-proposals/oc-complete-002-hassler-release-lifecycle.yml`. An owner or a
workflows-permitted actor can move it to
`.github/workflows/oc-complete-002-hassler-release-lifecycle.yml` unchanged. The
same file documents the one-line path addition needed in
`.github/workflows/calyx-hassler-intake-discovery.yml`.

## Owner gate

Live re-audit of current production readiness/release state could not be
performed in this session, and the exact upload therefore could not be taken
further.

- **Blocker:** this execution environment has neither `CALYX_BACKEND_URL` nor
  `CALYX_OWNER_ACCESS_CODE`, and its GitHub token cannot reach the Actions API
  (`HTTP 403: Resource not accessible by integration` on
  `/actions/workflows/calyx-hassler-intake-discovery.yml`), so the credentialed
  read-only discovery workflow could not be dispatched either.
- **Next executable action:** dispatch **CALYX Hassler Intake Discovery**
  (`workflow_dispatch`) on this branch. It runs GET-only against the deployed
  backend using the existing `vars.CALYX_BACKEND_URL` and
  `secrets.CALYX_OWNER_ACCESS_CODE`, and now uploads a schema-1.2 artifact
  containing the lifecycle classification, the downstream enumeration, and an
  owner-exception receipt if the release is still absent. That artifact is the
  live evidence this issue requires.
- **Who:** the repository owner, or any actor with Actions dispatch permission.
- **If discovery reports `ABSENT`:** the bounded upload action is already
  prepared and guard-validated in `scripts/upload_hassler_release_guarded.py`.
  Executing it is a production write and remains an explicit owner decision
  requiring `--execute` and
  `CALYX_HASSLER_UPLOAD_CONFIRMATION=UPLOAD_WORLD_ORCHIDS_26_08`.

## Remaining after this slice

- Live production re-audit and, if authorized, the bounded exact-release upload.
- Post-intake smoke gate, bounded staging checkpoint, change report, and
  idempotency/resumability verification against the real release (the contracts
  exist; live evidence does not).
- A real read-only downstream count adapter so `affected_records` moves from
  `unavailable` to observed counts.
- Portfolio-level status projection consuming `status_block`.
- Promotion of `docs/ci-proposals/oc-complete-002-hassler-release-lifecycle.yml`
  into `.github/workflows/` by a workflows-permitted actor.
