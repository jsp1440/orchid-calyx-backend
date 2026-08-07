# BUILD-BRAIN-114I — Current-main autonomous runtime consolidation

## Objective

Reconcile the validated autonomous-engineering runtime onto the current authoritative `main` after main advanced through Canonical Brain R2 and University work, without merging stale ancestry or weakening governance.

## Current-main baseline

At branch creation, `main` already contained the authoritative repository evidence reader and isolated-workspace patch executor. The older PR #551 had become conflict-prone because `main` advanced after its validation.

## Implemented on this clean current-main branch

- durable bounded per-job `input_json` manifests;
- canonical input-aware work fingerprints and snapshot redaction to digest/key metadata;
- program API support for governed job inputs;
- reserved identity/governance keys cannot be overridden by persisted job inputs;
- assignment factory grants `workspace_write` only to `isolated_workspace_patcher`;
- assignment factory grants `repository_code_execution` only to `isolated_workspace_executable_validator`;
- authoritative read-only static validator with exact postimage SHA-256 and Python parse/compile checks;
- supervisor-gated executable validator restricted to fixed internal `pytest` and `ruff` presets;
- canonical request digest binding repository, autonomy branch, exact checkout commit, sandbox assertions, preset, targets, exact target hashes, and effective timeout;
- supervisor authorization must return the same request digest; stale/replayed evidence fails closed before subprocess launch;
- default registry cannot claim executable-validation work without an injected trusted supervisor;
- forward-compatible database migration for persisted job inputs;
- focused current-main CI gate covering compile, Ruff, evidence/patch/executable-validation regressions, migration compatibility, and diff hygiene.

## Authoritative validation evidence

Code head `ec652c986a16544b4afdadb67fcffd3993382f8b` was validated by real GitHub-hosted Actions on 2026-08-07.

- BUILD-BRAIN-114I run `31214124007`: **success** — checkout, Python setup, dependency install, compile, Ruff, focused autonomy regressions, migration compatibility, and diff hygiene all executed and passed.
- BUILD-BRAIN-114C run `31214123974`: **success**.
- BUILD-BRAIN-114B run `31214123990`: **success**.
- BUILD-BRAIN-114A run `31214123943`: **success**.
- BUILD-BRAIN-108-113A run `31214123912`: **success**.
- CALYX-AGENT-003 run `31214124100`: **success**.
- BUILD-088E run `31214123940`: **success**.

The documentation-only commit recording this evidence does not expand runtime authority. Any subsequent code change requires a fresh successful BUILD-BRAIN-114I validation run before promotion.

## Safety boundary

The repository does not self-authorize an OS sandbox. Production executable validation still requires an external trusted supervisor that actually enforces network isolation, credential removal, subprocess confinement, and repository read-only behavior before issuing authorization.

No arbitrary caller-provided shell or argv, package installation, network, credentials, Git mutation, commit, push, Calyx-created PR, merge, deployment, publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation is authorized.

## Disposition

Staged as PR #562, current-main-derived and draft. The earlier conflict-prone #551 is superseded once this documentation-only head revalidates. Merge remains an explicit governance/release decision.
