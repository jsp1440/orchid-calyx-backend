# CI-BASELINE-001 — Canonical Calyx Journalism HTTP contract

## Demonstrated failure

After the BUILD-051 schema repair, the broad diagnostic fell to 26 failures. Eleven were all from the historical `tests/test_calyx_journalism_mvp_001.py` HTTP section, which still calls the retired `/api/calyx-journalism/*` route family.

Current `main` intentionally mounts Journalism under the authenticated Brain surface. `tests/test_calyx_journalism_brain_routes.py` is explicitly the canonical Brain-route contract and requires `/brain/journalism/*`. `docs/architecture/CALYX-JOURNALISM-003.md` also documents authenticated `/brain/journalism/...` retrieval routes and owner-scoped durable records.

Reintroducing a second legacy API surface would duplicate governed functionality and weaken the current routing contract merely to satisfy stale tests.

## Repair

BUILD-087B validation now separates the useful historical service tests from the obsolete HTTP contract:

- historical schema, preset, evidence-preview, generation, and Markdown-export tests continue to run as a blocking check via `tests/test_calyx_journalism_mvp_001.py -k 'not http'`;
- current authenticated HTTP behavior is a blocking check via `tests/test_calyx_journalism_brain_routes.py`;
- the repository-wide diagnostic ignores the historical MVP file so its retired `/api/calyx-journalism/*` tests no longer count as current-main regressions.

This is contract supersession, not test deletion: the durable current Brain-route suite is the authoritative HTTP replacement while the old non-HTTP behavior remains validated.

## Governance

No legacy route is restored. No auth is weakened. No external model, publication action, deployment, migration activation, credential change, taxonomy activation, or production Knowledge Graph mutation is introduced.

## Validation target

The exact head must pass the canonical Journalism blocking checks, BUILD-087B focused/regression checks, BUILD-088E, CI baseline, and workflow governance. The previous broad baseline was `26 failed, 1969 passed, 16 skipped`; removing the eleven stale HTTP failures should reduce the diagnostic to 15 current failures, modulo test-count changes from excluding the historical file whose non-HTTP tests are now executed separately as a blocking gate.
