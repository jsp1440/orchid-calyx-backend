# BUILD-BRAIN-108 — Governed Executor Boundary

## Intent
Provide the smallest executable boundary between a governed Calyx assignment and a verifiable execution receipt without granting shell, network, merge, deployment, publication, credential, or production Knowledge Graph authority.

## Delivered contracts
- `GovernedAssignment`: immutable assignment identity, objective, inputs, requested capabilities, evidence URIs, timeout, cancellation state, and optional expected input checksum.
- `ExecutorAdapter`: provider-neutral execution protocol.
- `DeterministicDryRunExecutor`: network-free and shell-free reference adapter.
- `ExecutionReceipt`: authoritative assignment/program/job identity, input/output checksums, terminal state/outcome, evidence URIs, output, and blocker code.
- Canonical JSON SHA-256 checksum calculation.

## Governance
The reference adapter supports validation, receipt production, and evidence-URI collection only. It fails closed for shell, network, merge, deploy, publish, credential access, production graph mutation, and every unregistered capability.

Cancellation and expired/invalid timeout conditions produce receipts without executing work. No private chain-of-thought is accepted or emitted.

## Reproducibility
Identical assignments produce identical receipts. Receipt output is independently checksum-verifiable. Evidence URI ordering is stable and duplicates are removed.

## Validation
Focused tests cover deterministic execution, input checksum mismatch, all prohibited capabilities, unsupported capabilities, cancellation, timeout, evidence URI validation, deduplication, and receipt verification.

Validation synchronization on 2026-08-06: an owner-authored documentation commit was added so GitHub Actions validates the exact branch head without the automation-origin approval gate. Merge remains contingent on all required workflows passing and no unresolved review findings.

## Dependency handoff
This boundary enables BUILD-BRAIN-109 to add durable leases, heartbeats, timeout recovery, retry eligibility, and stale-worker rejection around a provider-neutral executor.
