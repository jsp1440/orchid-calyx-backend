# BUILD-BRAIN-114I Safe Subset — Current Main

Date: 2026-08-07
Base main: `cafe087f75189c62689cef42c30b84d52a1d2fc2`
Source lineage: stale/draft PR #562

## Objective

Recover the independently useful, non-executable portions of BUILD-BRAIN-114I onto current main without bypassing the previously enforced repository-code-execution boundary.

## Included

- bounded canonical per-job input manifests persisted as `input_json`;
- input-aware work fingerprints, so jobs with materially different manifests are not deduplicated as identical work;
- request/API projection of bounded input manifests;
- assignment construction that merges persisted inputs only after reserved-key protection;
- snapshot metadata that exposes only manifest presence, SHA-256 digest, and key names rather than raw values;
- forward-compatible idempotent migration for `input_json`;
- read-only static workspace validation for allowed `app/`, `tests/`, and `docs/brain/` targets;
- hash binding, UTF-8 validation, bounded file/byte counts, Python AST parse/compile validation, revision checks, and isolation-marker checks;
- authoritative registry exposure of the static validator with `repository_code_execution=false`.

## Explicit exclusion

Executable repository validation remains excluded from this release.

The following PR #562 surfaces are intentionally not ported:

- `app/calyx_orchestrator/sandboxed_validation_executor.py`;
- `app/calyx_orchestrator/sandbox_authorization.py`;
- trusted-supervisor injection into the executor registry;
- the `repository_code_execution` requested capability;
- subprocess/shell-based repository test execution.

Current authority state:

- `repository_code_execution_authorized: false`
- automatic merge: false
- deployment: false
- publication: false
- taxonomy activation: false
- production database mutation: false
- production Knowledge Graph mutation: false

## Static-validation contract

The static validator is authoritative only for bounded read-only inspection. It does not import repository target modules, invoke subprocesses, invoke a shell, access the network, or write files. Python targets are syntax-checked using AST parsing and compilation of the parsed AST object; target file content itself is not imported or executed.

## Validation plan

`BUILD-BRAIN-114I Safe Subset` requires:

1. Python 3.13 compile of every changed autonomy module and focused test;
2. Ruff on the changed surface;
3. focused persisted-input/static-validation tests plus existing autonomous-cycle, repository-evidence, and isolated-patch regressions;
4. migration compatibility assertions;
5. explicit filesystem/source checks proving executable-validation modules are absent and no registry role has `repository_code_execution=True`;
6. this Brain boundary smoke;
7. `git diff --check`.

Fresh PR/exact-head run identifiers will be recorded before release.

## Remaining BUILD-BRAIN-114I work

The executable-validation portion of #562 remains a separate trust-boundary problem. Repository code alone cannot prove real OS-level network isolation, credential removal, subprocess confinement, and repository read-only enforcement. It must not be merged or reconstructed through an alternate Git path merely to avoid the prior safety/tooling block.
