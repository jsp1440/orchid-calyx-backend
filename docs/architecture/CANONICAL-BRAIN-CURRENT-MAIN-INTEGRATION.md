# Canonical Brain — Current Main Integration

## Purpose

Rebuild the validated Canonical Brain surface directly on current `main` so it integrates with the repository's newer Calyx orchestration runtime without replaying stale stacked ancestry.

## Why this replacement was required

The earlier stabilization slices were individually validated, but `main` continued advancing and added authoritative Calyx runtime components including governed assignment, dry-run execution, artifact registration, review eligibility, Brain candidate capture, Mission Control portfolio infrastructure, and an authoritative-executor boundary. Extending the old stack would have required copying newer runtime modules backward and would have created parallel or stale implementations.

This integration therefore transfers the validated Canonical Brain surface onto current `main` and uses the current Calyx runtime as the authoritative execution/evidence layer. The initial transfer was applied atomically as a single Git tree/commit so file identity was preserved without replaying stale branch history.

## Canonical Brain responsibilities

- canonical architecture, intent, decision, relationship, and search registry;
- deterministic snapshots and candidate persistence;
- constitutional build-admission rules;
- governed build queue and deterministic assignment records;
- non-authoritative preflight boundary;
- leases, heartbeat, timeout classification, bounded recovery candidates, and cancellation receipts;
- bridge from governed queue state to the existing Calyx dependency scheduler;
- authoritative-receipt-gated Canonical completion recording;
- translation of verified, allowlisted authoritative Calyx execution receipts into Calyx artifact, review, and Brain candidate-capture contracts.

## Existing Calyx responsibilities reused

Canonical Brain does not duplicate the following current-main components:

- `app/calyx_orchestrator/scheduler.py` — dependency, critical-path, and capacity scheduling;
- `app/calyx_orchestrator/executor.py` — capability enforcement, deterministic preflight receipts, and executor contracts;
- `app/calyx_orchestrator/dry_run_service.py` — release-after-preflight semantics so dry runs cannot complete real jobs;
- `app/calyx_orchestrator/executor_registry.py` — the authoritative executor allowlist;
- `app/calyx_orchestrator/artifact_registry.py` — immutable artifact provenance, checksum, evidence, and lineage;
- `app/calyx_orchestrator/review_eligibility.py` — review classes, self-approval prevention, and release eligibility;
- `app/calyx_orchestrator/brain_capture.py` — reviewed evidence-backed candidate Brain capture;
- current Calyx assignment, authoritative execution, and Mission Control portfolio infrastructure.

## Non-authoritative preflight correction

Current `main` explicitly distinguishes deterministic dry-run validation from authoritative execution. The inherited Canonical Brain adapter previously returned a Canonical `completed` receipt from a dry run. That path is removed in this integration.

`app/canonical_brain/executor.py` now wraps the current Calyx deterministic executor and returns an `ExecutionResult` with `dry_run=true` and `authoritative=false`. It does not create a Canonical completion receipt.

## Canonical completion correction

A second promotion path existed after the preflight fix: `GovernedOrchestrator.record_completed()` still accepted raw evidence URI(s) and an output checksum. A caller could therefore take checksum/evidence values from a non-authoritative preflight result and manually advance a Canonical queue item to `completed`.

That API has been replaced with authoritative receipt completion. A Canonical assignment may now transition from `running` to `completed` only when all of these conditions hold:

1. a current Calyx `ExecutionReceipt` passes `receipt.verify()`;
2. the supplied executor role resolves through the current `AuthoritativeExecutorRegistry`;
3. the registered executor is not authorized for external side effects;
4. receipt `executor_key` matches the allowlisted executor exactly;
5. the Canonical assignment agent ID normalizes to the same role key (for example `agent:autonomy-probe` → `autonomy_probe`);
6. receipt state and terminal outcome are both delivered;
7. receipt assignment ID equals the Canonical assignment ID;
8. receipt job key equals the Canonical build ID;
9. receipt evidence URI(s) and a full output checksum are present.

A successful Canonical completion receipt is marked `authoritative=true` and records the verified executor key. Started receipts remain non-authoritative.

This role binding is deliberately restrictive. At the current `main` revision the only autonomous authoritative role is `autonomy_probe`, so ordinary architecture agents such as `agent:brain-engineer` and `agent:atlas-engineer` cannot be automatically marked completed. Expanding autonomous engineering completion therefore requires an explicit future change to the Calyx authoritative executor registry rather than a change in Canonical Brain alone.

## Authoritative evidence correction

The first current-main evidence bridge accepted a Canonical `ExecutionReceipt` that had a completed outcome, evidence URI(s), and checksum. That was insufficient because the Canonical receipt itself did not prove which executor produced the completion.

The bridge now accepts the current Calyx `ExecutionReceipt` and an executor role key. It resolves that role internally through a fresh `AuthoritativeExecutorRegistry` and requires all of the following before constructing any artifact or Brain candidate record:

1. the role is currently registered as authoritative;
2. the registered executor is not authorized for external side effects;
3. the receipt `executor_key` exactly matches the allowlisted executor;
4. `receipt.verify()` passes its output-checksum and state/outcome invariants;
5. state is `DELIVERED` and terminal outcome is `DELIVERED`;
6. evidence URI(s), input checksum, and output checksum are present;
7. review requester identity is explicit and distinct from the verified executor producer.

Callers cannot pass a fabricated `RegisteredExecutor(authoritative=True)` object into this boundary. Authority is resolved inside the bridge from the current Calyx allowlist.

The bridge also no longer accepts caller-supplied Brain build, agent, or producer identities. `build_id` is derived from the verified receipt `job_key`; producer identity is derived as `executor:<executor_key>`; executor role identity comes from the authoritative registry. This prevents a valid receipt from being relabeled as evidence for another Brain build or producer.

Even after all execution checks pass, the result remains a candidate-only artifact. Existing Calyx review eligibility and `BrainCandidateStore` gates remain authoritative, and the generated record is explicitly `published=false`.

## Safety boundaries

- autonomous merge, deployment, publication, credential access, and production Knowledge Graph mutation remain prohibited;
- deterministic preflight cannot complete a real job;
- raw evidence/checksum values cannot complete a Canonical build;
- non-allowlisted or mismatched executors cannot complete Canonical builds or become Brain execution evidence;
- Canonical assignment agent role must match the allowlisted authoritative executor role before completion;
- external-side-effect executor authority is rejected by both Canonical completion and evidence capture;
- build and producer identity cannot be supplied independently of the verified receipt/executor;
- completed execution receipts require evidence URI(s) and checksums before evidence packaging;
- review requester and verified executor producer must be distinct;
- candidate capture remains unpublished and subject to the existing Calyx review gates;
- scheduler and evidence bridges are projections/translation boundaries, not new authorities.

## Validation lineage

Earlier clean slices established passing compile, Ruff, and focused pytest evidence for the registry, governance, queue/orchestration, executor/lease, and scheduler-bridge layers. The current-main integration must pass the complete `tests/test_canonical_brain_*.py` suite against the latest repository before it supersedes those drafts.

The authoritative evidence bridge/test files and the authoritative Canonical completion module were independently compiled with `python -m py_compile` in the implementation environment and passed syntax compilation. Ruff is not installed in that environment, so lint is not claimed as locally validated.

## GitHub-hosted runner incident — 2026-08-07

The CI failure mode has been isolated beyond the Canonical Brain code path.

Evidence:

- PR #516 head `65d6de2c157d755751f94a8a1b08386ca37d94a1` successfully completed seven GitHub Actions workflows immediately before the incident window, including BUILD-088E Validation.
- PR #525 then began producing `failure` conclusions where the job object contained `steps=null` and never reached checkout or any validation command.
- unrelated PR #527 exhibits the same zero-step failure across multiple existing workflows.
- a temporary `Actions Runner Smoke` workflow containing only one `ubuntu-latest` job and one `echo` step was added to PR #525. The workflow was parsed and queued, but the job completed with `failure` and `steps=null`; its only echo step never instantiated.
- the temporary smoke workflow was removed after the diagnostic result was captured.

This rules out Canonical Brain application code, Python version, package installation, cache behavior, checkout, secrets, pytest, and Ruff as causes of the **zero-step** termination.

The remaining boundary is GitHub-hosted runner allocation or repository/account Actions policy. Because the repository is private and the incident began after substantial successful Actions activity, Actions minutes/spending/billing is a plausible explanation, but it is not proven by the available API. Runner policy or account-level Actions restrictions remain possible alternatives.

The incident is tracked in GitHub issue #533. PR #525 must remain draft and unmerged until GitHub-hosted runner execution is restored and authoritative compile/Ruff/pytest can execute on the current head.
