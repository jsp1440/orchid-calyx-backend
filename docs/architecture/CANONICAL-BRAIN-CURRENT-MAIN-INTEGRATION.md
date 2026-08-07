# Canonical Brain — Current Main Integration

## Purpose

Integrate Canonical Brain with the repository's authoritative Calyx runtime without duplicating scheduler, executor, evidence, review, capture, or Mission Control infrastructure.

## Canonical Brain responsibilities

Canonical Brain owns:

- canonical architecture, intent, decision, relationship, and search registry;
- deterministic snapshots and candidate persistence;
- constitutional build-admission rules;
- governed build queue and deterministic assignment records;
- non-authoritative preflight projection;
- leases, heartbeat, timeout classification, bounded recovery candidates, and cancellation receipts;
- translation from governed queue state into existing Calyx scheduling contracts;
- authoritative-receipt-gated Canonical completion recording;
- translation of verified authoritative Calyx execution into artifact, review, and candidate-Brain contracts.

## Existing Calyx authorities reused

Canonical Brain does not replace:

- `app/calyx_orchestrator/scheduler.py` — dependency, critical-path, and capacity scheduling;
- `app/calyx_orchestrator/executor.py` — capability enforcement and execution receipts;
- `app/calyx_orchestrator/dry_run_service.py` — nonterminal dry-run/preflight semantics;
- `app/calyx_orchestrator/executor_registry.py` — authoritative executor allowlist;
- `app/calyx_orchestrator/artifact_registry.py` — immutable artifact provenance and lineage;
- `app/calyx_orchestrator/review_eligibility.py` — review eligibility and self-approval prevention;
- `app/calyx_orchestrator/brain_capture.py` — reviewed candidate Brain capture;
- existing Calyx Mission Control and program-worker runtime.

## Governance corrections

### Dry-run completion

Canonical preflight delegates to the Calyx deterministic executor and returns `dry_run=true`, `authoritative=false`. It cannot create a Canonical completion receipt.

### Canonical completion

`GovernedOrchestrator.record_completed()` no longer accepts caller-supplied evidence URI(s) and checksum as sufficient proof of completion.

Completion now requires:

1. a current Calyx `ExecutionReceipt` that passes `verify()`;
2. an executor role resolved through `AuthoritativeExecutorRegistry`;
3. no external-side-effect authority;
4. exact executor-key match;
5. Canonical assignment agent-role match;
6. delivered state and delivered terminal outcome;
7. exact assignment-ID match;
8. exact receipt `job_key` to Canonical build-ID match;
9. evidence URI(s) and full checksums.

Ordinary architecture agents therefore do not gain autonomous completion authority through Canonical Brain alone.

### Execution evidence provenance

The evidence bridge accepts the current Calyx authoritative receipt rather than trusting a Canonical state receipt.

It derives:

- executor authority from `AuthoritativeExecutorRegistry`;
- build identity from receipt `job_key`;
- producer identity from verified executor key;
- executor role from the registry.

Caller-supplied executor authority, build identity, agent identity, and producer identity are not accepted as independent trust claims.

Even valid execution evidence remains candidate-only and `published=false` until existing Calyx review eligibility permits candidate capture.

## Public receipt types

Package exports distinguish the two trust domains:

- `CanonicalExecutionReceipt` — Canonical queue/orchestration state;
- `CalyxAuthoritativeExecutionReceipt` — Calyx authoritative executor evidence.

`ExecutionReceipt` remains a compatibility alias for `CanonicalExecutionReceipt`.

## Validation

Authoritative GitHub validation recovered after runner incident #533.

Validated code head:

`5511fa059657b8b87e6031b048a79362bfef46b1`

Canonical Brain Validation run #109 / Actions run `31209013612` checked GitHub's PR merge ref against then-current `main` (`7eb323e764f7447431b1c7d90bed11bbe5fba53e`).

Results:

- compile: passed;
- Ruff: passed;
- pytest: **52 passed**;
- validation receipt emission: passed;
- `validated_tree_sha256`: `1e1429a09fac210e88dd7a03f8484d8ad3e40fcc2563089972c1049f5a023837`.

Independent BUILD-088E Validation run #887 also passed.

The receipt is recorded in `PR-525-AUTHORITATIVE-VALIDATION-RECEIPT.md`.

## Runner incident #533

Issue #533 is closed as recovered. During the incident, unrelated GitHub-hosted jobs terminated with `steps=null`, including a zero-dependency echo probe. Runner execution later resumed and real validation steps completed successfully. The exact GitHub-side cause was not observable and is intentionally not attributed to billing or policy without evidence.

Future zero-step failures should be diagnosed as runner/infrastructure failures before application code is modified.

## Safety boundaries

- no autonomous merge;
- no deployment;
- no publication;
- no credential access by Canonical validation or preflight;
- no production database mutation;
- no taxonomy activation;
- no production Knowledge Graph mutation;
- no external-side-effect executor may be promoted through these bridges;
- candidate capture remains review-gated and unpublished.

PR #525 is review-ready but unmerged. Any material change to Canonical Brain or its Calyx authority dependencies before merge requires validation against the new merge ref.
