# Orchid Continuum Continuous-Completion Health Contract

This document defines the repository-level invariants required for autonomous continuous completion. It is intentionally provider-independent and applies to both backend and frontend completion planes.

## Canonical execution states

An issue may occupy at most one executable lifecycle state at a time:

- `oc-queued` — eligible for selection, subject to policy and dependency gates.
- `oc-running` — atomically leased to exactly one execution lane.
- `oc-validating` — execution output exists and exact-head validation is pending or in progress.

The following labels are non-executable and must exclude `oc-queued`, `oc-running`, and `oc-validating` unless a repository-specific transition is performed atomically in the same operation:

- `oc-runtime-backoff`
- `oc-repair-backoff`
- `oc-blocked`

## Queue and lease invariants

1. `oc-queued` must not coexist with `oc-running`.
2. `oc-queued` must not coexist with `oc-validating`.
3. Executable states must not coexist with runtime/repair backoff or blocked states.
4. A backoff or blocked issue must not be selected for execution.
5. Selection must atomically transition the selected issue from `oc-queued` to `oc-running` before execution output is emitted.
6. Every `oc-running` issue must have exactly one current lease owner.
7. A lease must identify its issue and should carry the material-change lineage used by the scheduler.
8. The same material-change fingerprint must not be dispatched twice concurrently or repeatedly without material change.
9. Stale/orphan leases must be recoverable without creating duplicate dispatch.

## Validation invariants

1. `oc-validating` must correspond to a concrete PR/head or equivalent immutable validation target.
2. CI used for advancement must be exact-head CI; stale success on an earlier head is insufficient.
3. A changed PR head invalidates prior validation evidence.
4. Failed, errored, or skipped exact-head CI on routine reversible work is an engineering exception and should enter bounded repair/revalidation without owner interruption.

## Detection is not escalation

Every completion-health snapshot exposes the canonical exception-policy decision. A detected anomaly is classified as one of:

- `none`
- `informational`
- `engineering_exception`
- `owner_exception`

The machine-readable decision fields are:

- `exception_class`
- `owner_decision_required`
- `owner_exception_category`
- `autonomous_repair_available`
- `independent_authorized_work_available`
- `should_interrupt_owner`

`should_interrupt_owner` may be true only when an owner-only protected boundary is the actual blocker and neither bounded autonomous repair nor independent authorized work can continue safely.

Routine queue contradictions, exact-head CI failures, stale/orphan leases, duplicate fingerprints, provider-disabled state with deterministic work available, and one blocked lane while other authorized lanes remain are engineering exceptions. They must not be promoted to owner interruptions merely because they were detected.

## Owner-only boundaries

The canonical exception policy recognizes these owner-only categories when they are the actual blocking decision:

- governance/constitutional authority change;
- scientific truth or provenance activation/mutation;
- sensitive-locality disclosure or policy change;
- credential or security authority change;
- new spending or paid-provider restoration;
- destructive or irreversible operation;
- production activation/health judgment;
- explicit integration-to-main promotion gate where current policy still requires it.

Integration-branch merges of green, reversible engineering remain governed by existing pre-authorization and are not owner exceptions by default.

## Provider-health invariants

1. Provider capacity failure is a provider-health condition, not a queue-state condition.
2. An unavailable provider must not cause a tight redispatch loop.
3. New spending must not be authorized by the autonomous control plane.
4. Provider degradation must not weaken scientific, provenance, sensitive-locality, security, destructive-operation, or governance safeguards.
5. If deterministic/no-API work remains, provider-disabled state is parked and that work continues without owner interruption.
6. Paid-provider restoration becomes an owner exception only when no safe authorized work remains and restoration is actually required to proceed.

## Operations-status projection

`scripts/oc_operations_status.py` exposes a stable, redacted `oc.operations-status.v1` payload suitable for Calyx/phone monitoring. It consumes the canonical health evaluation rather than reimplementing state logic.

The projection includes queue/running/validating/backoff IDs and counts, active lane/lease age data, exact-head validation targets, autonomous PR CI state, provider degradation, integration readiness, structural violations, and the six machine-readable exception decision fields above.

Unknown fields are discarded. Provider credentials, secrets, private provenance, sensitive locality, internal exception details, and other non-allowlisted input are not surfaced.

## Operating consequence

Repair first. Continue independent authorized work second. Escalate only when a protected owner-only boundary is the actual blocker.
