# Brain module lifecycle: isolated contract evidence

Classification: **NEW focused acceptance slice**, not a competing scheduler.
Evidence tier: **LOCAL_INTEGRATION_VALIDATED** only.

## Source boundaries

Checked against GitHub on 2026-10-08:

- Backend integration: `4a2b48dd05d7f578eee20aff248c923a585eceb8`.
- Backend main: `f32d508677ffe3765c9e8c380d7d2619023ee6eb`.
- Frontend main: `6241b2f7a579d91f48399bd78c0c4659cb1b9923`.
- Brain main: `b6833c056dceb6678b586cbbaddb96d4a26a9e85`.

The requested `scripts/oc_brain_pulse.py` is on backend integration, not the
current backend main. All changes are isolated from active agent branches.
Open PRs were inspected; backend bounded-executor PR #1784 and Brain mission
boundary PR #213 do not change the repaired paths. No active PR was altered.

## Failures reproduced before repairs

1. Brain's actual `build_reasoning_envelope` output fails its actual
   `validate_calyx_reasoning_envelope` consumer:
   `Calyx Reasoning Envelope: missing required fields: reasoning_id`.
   The new Brain producer/consumer regression failed before adding the missing,
   deterministic candidate-derived identity. Consumer/governance gates were not
   weakened. This repair belongs in the separate Brain draft PR.
2. Six backend regressions failed with `completed_jobs == 1`, expected `0`,
   for blocked, timed-out and cancelled receipts, both at budget exhaustion and
   on the idle return. The cycle now counts delivered receipts as completed and
   separately reports all terminal receipts as `settled_jobs`. Blocker/cancellation
   evidence and dependency blocking are retained, not converted to success.

The initial 38 existing focused checks passed; the defects were exposed by new
composition/accounting checks, not inferred from unrelated failures.

## What the new tests actually execute

`tests/test_brain_module_lifecycle_contracts.py` uses:

- the real provider-free pulse, deterministic reasoning/discovery fixture store,
  and module advisory operation;
- constitutional admission, canonical architecture/role assignment and the
  existing scheduler bridge;
- the persistent program worker, live lease acquisition, existing repository
  evidence and static-validation executors, receipt bridge, durable settlement,
  canonical completion and downstream eligibility release;
- ten jobs across Lexicon, Literature, Research Station, Atlas and University:
  one repository-evidence job and one syntax/hash-validation job per module;
- a real disposable Git checkout containing copies of the current module source;
  a file-backed disposable SQLite database, reopened across each turn;
- an independent session at executor entry to witness the persisted owned lease
  and reject a competing claim. Lease tokens are not emitted; witnesses retain
  fingerprints only.

Negative checks reject premature canonical completion, wrong lease/worker/job
identity, changed source hashes, and owner-governed publication/deployment/merge/
production-KG admission. A failed module check releases its lease into backoff
without unlocking the next module.

The static validator intentionally rejects `runtime/` paths. During fixture
construction it rejected the Atlas source-registry target with
`STATIC_VALIDATION_PATH_NOT_ALLOWED`; the test was corrected to validate the
existing `app/atlas_intelligence/assembler.py`, without broadening the allowlist.

`tests/test_oc_work_materialize.py` additionally runs the real multi-module pulse
through the existing fake GitHub transport with a lagging search index. It checks
filing, routing, owner-gated lineage, repeated discovery and overlapping stale
plans without duplicate issues or silent scientific-gap resolution.

`tests/test_brain_cross_repository_contracts.py` checks the repaired actual Brain
producer against its actual consumer, the byte-identical frontend/backend
completion contract, Brain evidence requirements, pinned frontend source
bindings, full-revision identities and mandatory failure reasons. These are
source-contract checks, not a frontend browser or deployed API certification.

## Verification

Backend focused run: **208 passed, 2 skipped, 1 deselected**.
The two pre-existing sibling-source checks skipped because their older
`OC_FRONTEND_CHECKOUT` / `OC_BRAIN_CHECKOUT` variables were not set; equivalent
checks in the new cross-repository suite ran against explicitly supplied current
checkouts. The existing unrelated app route-mount import test was deselected.
Brain focused run: **10 passed**. Changed Python files pass Ruff's
`E4,E7,E9,F` checks and both repositories pass `git diff --check`.

Reproduce from the backend checkout (with a repaired Brain sibling checkout):

```sh
# Use the Python installation's site-packages directory, if needed by Replit.
PYTHON_SITE=/home/runner/workspace/.pythonlibs/lib/python3.11/site-packages
env -i PATH="$PATH" HOME=/tmp PYTHONPATH="$PYTHON_SITE" \
  PYTHONDONTWRITEBYTECODE=1 DATABASE_URL=sqlite+pysqlite:///:memory: \
  OC_BRAIN_CONTRACT_ROOT=/path/to/repaired-brain-checkout \
  OC_FRONTEND_CONTRACT_ROOT=/path/to/current-frontend-checkout \
  python3 -m pytest -q \
  tests/test_brain_cycle_terminal_accounting.py \
  tests/test_brain_module_lifecycle_contracts.py \
  tests/test_brain_cross_repository_contracts.py \
  tests/test_canonical_brain_scheduler_bridge.py \
  tests/test_canonical_brain_orchestration.py \
  tests/test_calyx_autonomous_program_cycle.py \
  tests/test_calyx_persisted_scheduler.py \
  tests/test_calyx_safe_autonomy_inputs_static_validation.py \
  tests/test_calyx_persisted_patch_execution.py \
  tests/test_oc_brain_pulse.py tests/test_oc_work_materialize.py \
  tests/test_oc_provider_free_validate.py \
  tests/test_oc_swarm_provider_free_worker.py \
  tests/test_cross_repo_completion_receipt_contract.py \
  -k 'not route_is_mounted'
```

Run Brain's `tests/test_reasoning_contracts.py`,
`tests/test_reasoning_envelope_integration.py` and
`tests/test_cross_system_integration_path.py` in a similarly cleared environment.
No production credentials are inherited by these test commands.

## Limits and remaining acceptance

The mapping from pulse candidates to program jobs in the lifecycle test is
**explicit test scaffolding**. The test does not add or certify an automatic
production pulse-to-program admission bridge. The one-job-per-turn driver is
also test scaffolding, not an unattended hosted scheduler proof.

These ten jobs are repository observations and syntax/hash checks, not ten
scientific discoveries, scientific validations, code repairs or live product
results. The prior timer harness's ten completed probe jobs remain a separate
lease/persistence proof. Neither proof establishes useful live cross-module
completion. A scientific gap remains in the next pulse even after repository
checks succeed; subtask success must never certify the parent scientific/coding
mission.

SQLite session fencing is not a PostgreSQL concurrency/stress certification.
The entire repository test suite, actual module browser flows, production
providers, live data, deployments and hosted scheduling were not exercised.
No production schema/data, paid provider, merge, deployment, scientific
publication or active agent branch/PR was changed.

**The Orchid Continuum is not declared live-ready or autonomous by this evidence.**
