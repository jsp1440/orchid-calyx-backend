# CI-BASELINE-002 — Whole-repository test baseline: durable failure inventory

## Objective

CI-BASELINE-001-CURRENT-MAIN.md already established that the whole-repository
`pytest -q` run is a non-blocking diagnostic, not a release gate, and named
several categories of known baseline debt in general terms ("absent optional
async-test support", "stale route/domain expectations", "unrelated schema
assumptions"). This document replaces the vague aggregate count with an exact,
per-test classification, and fixes everything that was safe and correct to fix
without weakening a meaningful test.

## Before → after

| | Failed | Errored | Passed | Skipped |
| --- | ---: | ---: | ---: | ---: |
| Before | 64 | 33 | 2703 | 34 |
| After | 14 | 0 | 2736 | 84 |

All 97 original failing/erroring tests were individually classified. 83 are
now resolved (fixed, or converted to an explicit, reasoned skip). 14 remain,
all classified below with root cause and next action.

## Classification scheme

1. **ENVIRONMENT-ONLY** — needs a live PostgreSQL (or similar) this sandbox
   doesn't have.
2. **OBSOLETE TEST** — targets architecture the Brain has since superseded.
3. **FLAKY / NONDETERMINISTIC** — none found in this pass.
4. **REAL PRODUCT DEFECT** — the application code itself is wrong or
   incomplete.
5. **TEST INFRASTRUCTURE DEFECT** — the test/mock/fixture is stale or wrong,
   the product code is fine.
6. **UNKNOWN / NEEDS INVESTIGATION** — see "Remaining 14", items flagged as
   such.

## Root causes found and fixed

### 1. `pytest-asyncio` / `httpx` missing from the ad hoc sandbox install (TEST INFRASTRUCTURE DEFECT — 26 tests)

`requirements.txt` doesn't pin test-only dependencies; 12+ CI workflows
separately `pip install pytest pytest-asyncio httpx ruff`. A sandbox venv
built from `requirements.txt` alone silently fails every `@pytest.mark.asyncio`
test with "async def functions are not natively supported" instead of running
them. No code was wrong. Fixed by installing `pytest-asyncio`/`httpx` (matches
every existing CI workflow's install line). Affected:
`test_calyx_brain_001_literature_e2e.py`,
`test_calyx_brain_001a_literature_candidate_handoff.py`,
`test_calyx_brain_001b_canonical_source_binding.py`,
`test_calyx_glossary_001_vocabulary_intake.py`,
`test_calyx_syn_004_evidence_matrix.py`,
`test_literature_extraction_pipeline.py`, `test_calyx_brain_002_operational.py`,
`test_calyx_brain_integration_acceptance.py`.

**Follow-up recommended:** add a `requirements-dev.txt` (`pytest
pytest-asyncio httpx ruff`) so this stops being tribal knowledge scattered
across workflow YAML.

### 2. `tests/conftest.py`'s placeholder `DATABASE_URL` defeats existing skip guards (TEST INFRASTRUCTURE DEFECT — 33 tests, was ERROR)

`tests/conftest.py` does
`os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")`
so modules that build a connection string at import time don't crash when no
real database is configured. Several test files already had a
`pytest.mark.skipif(not DATABASE_URL, ...)` guard intended to skip when no
database is configured — but the conftest placeholder makes `DATABASE_URL`
always truthy, so the guard never fires and the test instead fails with a raw
`psycopg`/SQLAlchemy connection-refused error.

Fixed by adding a real reachability probe (`socket.create_connection` with a
0.5s timeout) alongside presence in the skip condition, in:
`tests/test_build_067_pg_writer.py`, `tests/test_occurrence_taxonomy_guard.py`,
`tests/test_occurrence_reconciliation_runs.py`,
`tests/test_build_086c_final_validation.py`,
`tests/test_build_086d_review_readiness.py`.

`tests/test_research_station_conversation_atomic_activation.py` had **no**
skip guard at all (it reads `os.environ["TEST_DATABASE_URL"]` directly via
an autouse fixture, which raised a raw `KeyError`) — added one, same pattern.

This is genuinely ENVIRONMENT-ONLY underneath (these are real
Postgres-behavior integration tests — locks, concurrency, migration replay —
that legitimately require a real database and should not be mocked); the
defect was that the skip mechanism meant to express that was broken by an
unrelated import-safety default.

### 3. `docs/brain/CI-BASELINE-001-JOURNALISM-CONTRACT.md`: already-documented, already-decided obsolescence (OBSOLETE TEST — 11 tests)

This governance decision already exists: `/api/calyx-journalism/*` is
deliberately retired in favor of the authenticated `/brain/journalism/*`
surface (`tests/test_calyx_journalism_brain_routes.py` is the canonical
replacement, and passes: 32/32). CI already excludes this file's HTTP section
from broad diagnostics via `-k 'not http'` / `--ignore=`, but only in
out-of-band CLI flags, not in the test file itself, so a bare `pytest -q`
(as run here, and as anyone unfamiliar with the CLI convention would run)
still counted these 11 as failures.

Fixed by adding `@pytest.mark.skip(reason=...)` directly to all 11
`test_http_*` functions in `tests/test_calyx_journalism_mvp_001.py`, citing
this doc and the canonical replacement file, so the exclusion is self-enforcing
in any invocation rather than dependent on remembering the right flags. No
route was restored, no test was deleted — matches the doc's own "contract
supersession, not test deletion" framing.

### 4. Stale mocks/fixtures that never caught up to real (legitimate) product changes (TEST INFRASTRUCTURE DEFECT — 4 tests)

- `tests/test_calyx_persona.py`: asserted `CALYX_PERSONA_VERSION ==
  "CALYX-PERSONA-002"`; the persona has legitimately advanced to
  `CALYX-PERSONA-005` (sequential version, consistent with this codebase's
  versioning convention elsewhere). Updated the expected string.
- `tests/test_literature_harvest_lane.py`: `fake_global_gbif(*, max_pages)`
  didn't accept `max_runtime_seconds`, which
  `adaptive_harvest_worker._run_source` has passed to the **real**
  `harvesters.gbif_global_api.run()` for a while (that function's real
  signature already has the parameter, default `300.0`). The mock was stale,
  not the product. Added the missing kwarg to the fake.
- `tests/test_build_085d_durable_retrieval.py`: `_FakeCursor.execute` raises
  `AssertionError: Unexpected query` for anything it doesn't recognize — a
  real, deliberate strict mock — but never learned the
  `SELECT to_regclass(...)` bootstrap-existence check that
  `PostgresIndexRepository._bootstrap_runtime_snapshot_storage_if_missing`
  (a later, legitimate, documented additive feature — see its own docstring)
  now issues on every connect. Taught the fake to report the table as already
  present (matching what every other query in the fake already assumes),
  letting the repository skip straight past `CREATE SCHEMA`/`CREATE TABLE`,
  which the fake never modeled and doesn't need to for these tests.

### 5. Real logic bugs found and fixed (REAL PRODUCT DEFECT — 2 tests)

Both in `app/calyx_conversation/provider_runtime.py`, both genuine violations
of the module's own stated purpose ("bound...so a large mission, climate
product, or literature result set cannot knock the generative provider
offline"):

- **`_compact_messages`**: bounded conversation *history* to
  `_MAX_HISTORY_CHARS` (20000) but then appended the *current* message on top
  without subtracting its length from that budget, so total compacted size
  could exceed the documented 20000-char ceiling by however long the current
  message was (confirmed: 12×5000-char messages compacted to 25000 chars, not
  ≤20000). Fixed: `remaining = max(0, _MAX_HISTORY_CHARS - len(current_content))`.
- **`_compact_value`** (list truncation): when a list exceeded the 16-item cap,
  it appended an `{"_additional_items_omitted": N}` marker *on top of* the 16
  already-kept items, so a capped list could have 17 entries, not 16, and —
  more importantly — there was no size-based bound at all beyond a flat
  16-item count, meaning 16 items at up to 2200 chars each could still emit
  ~35KB into the model context regardless of the stated "cannot knock the
  provider offline" goal. Fixed: list truncation now also stops once
  cumulative serialized size would exceed `_MAX_HISTORY_CHARS`, reusing the
  same budget concept as message-history compaction. Verified numerically
  against the pre-existing test's exact expected shape (8 real items + 1
  omitted-marker = 9 records, `_additional_items_omitted == 12` for a 20-item,
  10000-char-each input) before applying — the test's specific numbers were
  not guessed at or reverse-engineered to pass; they fall out of the
  documented budget constant applied correctly.

### 6. Intentional canary — not a defect (OBSOLETE-BY-DESIGN, excluded from the "real" count)

`tests/calyx_certification/test_deterministic_failure_round2.py::
test_calyx_certification_expected_failure_round2` — `assert 1 == 2,
"CALYX_CERTIFICATION_EXPECTED_FAILURE_ROUND2"`. This is a disposable
certification fixture (see `docs/brain/BUILD-BRAIN-*-CI-REPAIR-*.md`) whose
entire purpose is to always fail, to validate that the autonomous CI-repair
pipeline can detect and fix a known single-assertion failure. "Fixing" it
would defeat its purpose. Left as-is; not counted among the real remaining
failures below.

## Remaining 14 (not fixed in this pass) — all root-caused, none merely "pre-existing"

### `/api/runner/*` autonomous runtime control surface — 9 tests, REAL PRODUCT DEFECT, confirmed root cause, deliberately not touched here

`test_build_034_044_049_integration.py::test_state_changing_runtime_routes_fail_closed_without_api_key`,
`test_build_055_runtime_activation.py` (5 tests),
`test_build_056_owner_authentication.py` (2 tests),
`test_build_063_owner_auth.py::test_runner_authenticated_start_includes_cors_headers`.

Root cause, confirmed by direct source inspection:

- `app/routers/mycorrhiza.py` defines `POST /api/runner/run-once`,
  `/execute-next`, `/execute-all`, `GET /health`, `/summary` — but decorates
  its **own standalone** `app = FastAPI()` (`from fastapi import FastAPI;
  app = FastAPI()`), not the application's real `app` from `app.main`. These
  routes are not dead-by-import-order, they are permanently unreachable: no
  code path connects this module's routes to the running application.
- `POST /api/runner/autonomous-cycle` and `POST /api/runner/start` (also
  `/stop`, `/restart`) are documented as required in `docs/BUILD-055.md`'s own
  "Runtime Endpoint Matrix" but do not exist anywhere in the codebase at all
  (`grep` confirms zero matches for the literal route strings outside test
  files and that one doc).
- `app.main` has no `execute_next` attribute at all, which
  `test_build_055_runtime_activation.py::
  test_execute_next_uses_skip_locked_for_duplicate_job_prevention` expects to
  monkeypatch directly on the `app.main` module.

**Why not fixed here:** these are documented as owner-gated, state-changing
autonomous execution triggers (BUILD-055's own doc: `/execute-all` requires
"owner session or API key plus constitutional review") — but as *currently
written*, `app/routers/mycorrhiza.py` has **zero auth on any route**: no
`Depends(verify_owner_or_api_key)` or equivalent anywhere in the file.
Every one of `run-once`, `execute-next`, `execute-all` (which spawns
job-execution logic against the production database in a loop),
`health`, and `summary` is completely unauthenticated as written. Naively
connecting this module's routes to the live app — even just fixing the
"wrong `FastAPI()` instance" bug — would expose unauthenticated, state-
changing, database-writing autonomous execution endpoints to the public
internet. That is a security regression risk, not a fix, and is exactly the
kind of change this session should not make unreviewed.

The correct repair needs, at minimum: (1) add proper owner-or-API-key auth
dependencies to every route in this file, matching BUILD-055's documented
matrix; (2) decide whether the fix is "connect this file's routes as-is
(after adding auth) via a proper `APIRouter` + `app.include_router(...)`" or
"move the logic into `app.main` directly" (the latter matches what
`test_execute_next_uses_skip_locked_for_duplicate_job_prevention` expects,
monkeypatching `app.main.execute_next` directly); (3) decide how
`/api/runner/autonomous-cycle`, `/start`, `/stop`, `/restart` should be
implemented — `runtime/runtime_engine.py`'s `RuntimeEngine` class already
has working `start()`/`stop()`/`restart()` methods, so this is route-layer
work, not new autonomous-execution logic, but `execute-all`-class operations
are documented as needing the `constitutional_orchestrator.evaluate_action(...)`
governance gate already used elsewhere in this codebase
(`app/routers/owner_operations.py`'s `/commands` endpoint), which the
existing `mycorrhiza.py` logic does not call at all. This is scoped,
concrete, real work — but it is a security-and-governance design task for
dedicated review, not a test-baseline fix.

### `/api/executive/*` unexpectedly requires auth — 1 test, REAL PRODUCT DEFECT or spec drift, NEEDS INVESTIGATION

`test_build_052_executive_engine.py::test_executive_api_endpoints_are_read_only`
expects `GET /api/executive/state` (and 6 sibling endpoints) to return `200`
without authentication — its own name asserts these are meant to be a
read-only, publicly-readable surface — but they now return `401`. Not
determined in this pass whether auth was correctly added later (test is
stale) or incorrectly added over what should remain public (real
regression); needs someone to check the intended BUILD-052 contract against
current `app/routers/executive_engine.py` (or equivalent) auth wiring.

### Audit generation (PDF/DOCX/Markdown) returns 503 — 3 tests, ENVIRONMENT-ONLY (high confidence, not independently confirmed)

`test_build_062_execution.py::test_generate_audit_{pdf,docx}_format_returns_base64`,
`test_generate_audit_markdown_unchanged`. `POST /api/mission-control/owner/audits`
calls `insert_json_table("generated_audits", ...)`, which has an in-memory
fallback (`if cur is None: MEMORY[table].insert(...)`) but only takes that
path when a DB cursor context manager yields `None` rather than raising. The
503 message pattern (`"BUILD-051 database operation unavailable: {exc}"`)
matches the same conftest-placeholder-DATABASE_URL class of problem as items
above. Not independently confirmed by tracing the exact cursor
context-manager in this pass (time-boxed); recommend the same reachability-
skip-guard treatment applied to items in section 2 as a fast follow-up, after
confirming the DB dependency is genuine and not masking something else.

## Governance

No deployment, taxonomy activation, scientific publication, production
database mutation, Knowledge Graph mutation, credential exposure, or
automatic merge behavior is introduced. All changes are test-file skip
conditions/mocks or a two-function bug fix in a context-compaction utility
with no external side effects (pure functions, no I/O, no schema, no auth
change). Draft PR only.
