# Orchid Continuum Swarm Controller

The Swarm Controller converts the continuously refilling Orchid Continuum portfolio into bounded parallel implementation waves.

## Current operating envelope — Swarm v4

- default capacity: 8 implementation workers;
- hard maximum: 12 workers per wave;
- bounded self-refill: at most 4 waves per activation by default;
- canonical `oc-queued` portfolio and priority policy remain authoritative;
- explicit issue dependencies gate dispatch before resource locking;
- fine-grained read/write resources govern safe concurrency;
- exact-head validation verifies actual changed files against each worker lease;
- workers target `oc-autonomous-integration`, never `main`;
- the planner performs no provider call, deployment, merge, scientific publication, taxonomy activation, credential change, spending, or production mutation.

## Evolution

**v1 — bounded parallelism.** Multiple completion workers run concurrently instead of serially.

**v2 — resource locking.** Product lanes are separated from semantic resources. Read/read work may run together; write/write and read/write conflicts are suppressed. Explicit `OC-SWARM-READS:` and `OC-SWARM-WRITES:` markers or `oc-resource-*` labels can replace inference.

**v3 — post-build enforcement.** Exact-head validation maps the PR's actual changed files back to semantic resources and rejects runtime/configuration writes outside the worker's durable write lease. Read authority never authorizes a write. Control-plane, schema, repo-global, and unknown-path changes fail closed unless explicitly authorized.

**v4 — dependency graph and continuous refill.** Work may declare durable issue dependencies, and newly available capacity is continuously re-evaluated through bounded refill waves plus repository state-change triggers.

## Swarm v4 dependency contract

An issue can declare:

```text
OC-SWARM-DEPENDS-ON: #1201, #1202
```

A dependency is satisfied only when the referenced issue is closed or carries `oc-done`. A missing referenced issue fails closed. Dependency cycles are detected; every cycle member remains blocked and the cycle is surfaced in the wave summary.

Dependency readiness is evaluated before resource locking. Therefore priority alone can never launch work whose prerequisite has not completed.

## Resource contract

Examples of resource keys include:

`taxonomy`, `occurrence`, `literature`, `images`, `molecular`, `habitat`, `geospatial`, `atlas`, `knowledge-graph`, `brain-reasoning`, `scientific-memory`, `research-station`, `frontend-api`, `security-observability`, `pollinator`, `mycorrhiza`, `traits`, and `conservation`.

The control plane has an exclusive `control-plane` resource. Unknown work falls back to a conservative coarse `lane-*` write lock.

Lock semantics:

- write + write on the same resource: conflict;
- read + write: conflict;
- read + read: allowed;
- conflicting candidates remain queued for a later wave;
- active `oc-running` workers reconstruct their resource locks before every new plan.

## Continuous refill

Swarm v4 is designed so a completed worker does not leave capacity idle until a person starts another run.

The controller responds to issue state/label changes, closed integration PRs, and a five-minute reconciliation pulse. Within one activation it may also dispatch another bounded wave when waiting work exists and workers have just completed. The refill chain has an explicit maximum-wave counter, so it cannot recurse indefinitely.

This is not permission to bypass dependencies or locks. Every refill reconstructs the repository snapshot from scratch and repeats canonical eligibility -> dependency readiness -> resource locking.

## End-to-end architecture

1. Read open and closed issue state plus open integration PRs.
2. Apply canonical queue, priority, blocked-state, owner-gate, repair, and durable-PR policy.
3. Build the explicit dependency DAG and fail closed on missing prerequisites or cycles.
4. Filter to dependency-ready candidates.
5. Reconstruct active semantic resource locks.
6. Admit only resource-compatible candidates up to bounded capacity.
7. Publish durable worker receipts containing reads, writes, and dependencies.
8. Run implementation workers in parallel on isolated branches.
9. Verify actual PR changed files against the worker's write lease.
10. Run ordinary exact-head tests and governance checks.
11. Let the independent integration supervisor decide whether validated reversible work may enter `oc-autonomous-integration`.
12. Reconcile again and refill newly free capacity.

## Protected boundary

Swarm execution does not authorize merge to `main`, production deployment, taxonomy activation, scientific publication, authoritative Knowledge Graph mutation, sensitive-locality disclosure, credential changes, spending, or destructive operations. Those boundaries remain governed independently.

## Activation

The controller is being developed on `oc-autonomous-integration`. Scheduled/event-driven swarm execution becomes operational only after the control-plane change is validated and intentionally promoted to the repository default branch. Until that promotion, the implementation can be tested without silently changing production orchestration.
