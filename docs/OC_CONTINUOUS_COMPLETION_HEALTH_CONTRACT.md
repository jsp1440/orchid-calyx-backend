# Orchid Continuum Continuous-Completion Health Contract

This document defines the repository-level invariants required for autonomous continuous completion. It is intentionally provider-independent and applies to both backend and frontend completion planes.

## Canonical execution states

An issue may occupy at most one executable lifecycle state at a time:

- `oc-queued` — eligible for selection, subject to policy and dependency gates.
- `oc-running` — atomically leased to exactly one execution lane.
- `oc-validating` — execution output exists and exact-head validation is pending or in progress.

The following labels are non-executable and MUST exclude `oc-queued`, `oc-running`, and `oc-validating` unless a repository-specific transition is performed atomically in the same operation:

- `oc-runtime-backoff`
- `oc-repair-backoff`
- `oc-blocked`

## Queue and lease invariants

1. `oc-queued` MUST NOT coexist with `oc-running`.
2. `oc-queued` MUST NOT coexist with `oc-validating`.
3. `oc-queued` MUST NOT coexist with `oc-runtime-backoff`.
4. `oc-queued` MUST NOT coexist with `oc-repair-backoff`.
5. A backoff or blocked issue MUST NOT be selected for execution.
6. Selection MUST atomically transition the selected issue from `oc-queued` to `oc-running` before execution output is emitted.
7. Every `oc-running` issue MUST have exactly one current lease owner.
8. A lease MUST identify the issue and a material-change fingerprint (issue state plus expected PR/head when applicable).
9. The same material-change fingerprint MUST NOT be dispatched twice concurrently or repeatedly without a material change.
10. Stale leases MUST be recoverable without creating duplicate dispatch.

## Validation invariants

1. `oc-validating` MUST correspond to a concrete PR/head or equivalent immutable validation target.
2. CI used for advancement MUST be exact-head CI; stale success on an earlier head is insufficient.
3. A changed PR head MUST invalidate prior validation evidence.
4. Failed validation may enter repair/backoff, but MUST NOT leave the item advertised as queued simultaneously.

## Provider-health invariants

1. Provider capacity failure is a provider-health condition, not a queue-state condition.
2. An unavailable provider MUST NOT cause a tight redispatch loop.
3. Already-authorized provider fallback MAY be used when repository policy permits it.
4. New spending MUST NOT be authorized by the autonomous control plane.
5. Provider degradation MUST NOT weaken scientific, provenance, sensitive-locality, security, destructive-operation, or governance safeguards.
6. When no provider can safely execute eligible work, the control plane MUST remain internally consistent and report a truthful parked/degraded state.

## Integration and promotion invariants

1. Routine green, mergeable, reversible engineering work is not an owner exception.
2. Integration-branch convergence may proceed under existing repository policy.
3. Integration-to-main promotion MUST preserve any explicit owner or constitutional gate already encoded by policy.
4. A green workflow conclusion alone is not sufficient evidence of healthy autonomy; queue, lease, duplicate-dispatch, and exact-head invariants must also hold.

## Owner-exception taxonomy

The autonomous system SHOULD continue without owner interruption unless one of these conditions is reached:

- owner policy or constitutional judgment is genuinely required;
- the autonomous control plane is stalled after reasonable self-repair;
- scientific or provenance integrity would be weakened;
- sensitive locality could be exposed;
- a security boundary is implicated;
- new paid spending is required;
- a destructive or irreversible operation is required;
- production health requires an owner decision;
- an existing explicit integration-to-main owner gate is reached.

Everything else should be handled as normal autonomous engineering work.

## Required health snapshot

Every completion pulse should be able to produce or derive a machine-readable snapshot containing at least:

- queued count and issue IDs;
- running count, issue IDs, lease IDs/owners, and lease ages;
- validating count, issue IDs, PR numbers, and exact head SHAs;
- runtime-backoff count and issue IDs;
- repair-backoff count and issue IDs;
- contradictory-state violations;
- stale leases;
- duplicate material-change fingerprints;
- provider availability/degradation state;
- open autonomous PRs and exact-head CI status;
- integration-to-main readiness;
- production/governance/protected-boundary exceptions.

A healer MUST NOT report success while any contradictory executable/backoff state remains. If an invariant cannot be restored safely, the health snapshot must fail closed and identify the blocking invariant.