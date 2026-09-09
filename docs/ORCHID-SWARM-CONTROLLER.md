# Orchid Continuum Swarm Controller

The Swarm Controller converts the continuously refilling Orchid Continuum portfolio into bounded parallel implementation waves.

## Swarm v3 operating envelope

- hard maximum: 12 implementation workers per wave;
- default requested capacity: 8 workers;
- canonical `oc-queued` portfolio and existing priority policy remain authoritative;
- durable PR suppression, owner gates, repair/backoff and blocked states remain authoritative;
- each worker uses the existing `orchid-completion-lane.yml` contract;
- workers target `oc-autonomous-integration`, never `main`;
- the planner performs no provider call, deployment, merge, scientific publication, taxonomy activation, credential change or production mutation;
- exact-head validation now verifies the worker's actual PR write-set against the resource lease that authorized the worker.

## Why resource locks

Swarm v1 conservatively allowed one worker per coarse product lane. That prevented collision storms, but it also meant two unrelated L3 jobs such as literature provenance and image provenance could not run together.

Swarm v2 separated **product lanes** from **resources**. Product lanes remain useful for reporting and fallback safety, while resource claims determine whether work can execute concurrently.

Examples of resource keys include:

`taxonomy`, `occurrence`, `literature`, `images`, `molecular`, `habitat`, `geospatial`, `atlas`, `knowledge-graph`, `brain-reasoning`, `scientific-memory`, `research-station`, `frontend-api`, `security-observability`, `pollinator`, `mycorrhiza`, `traits`, and `conservation`.

The control plane itself has a special exclusive `control-plane` resource.

## Lock semantics

- write + write on the same resource: conflict;
- read + write on the same resource: conflict;
- read + read on the same resource: safe to run in parallel;
- a candidate that conflicts with an active worker or an earlier selected worker is skipped for that wave, not destroyed or relabelled;
- unclassified work falls back to an exclusive coarse-lane lock such as `lane-l4`, preserving the conservative v1 behavior;
- control-plane work is globally exclusive.

Issue authors can override inference with explicit durable body markers:

```text
OC-SWARM-READS: taxonomy, literature
OC-SWARM-WRITES: atlas, geospatial
```

A label such as `oc-resource-literature` can also declare an exclusive resource. Explicit body markers take precedence over labels and keyword inference.

## Swarm v3 — post-build write-set enforcement

Pre-build resource classification is only a scheduling prediction. Swarm v3 closes that gap by enforcing the lease after code exists.

When the swarm claims a worker, it publishes a durable issue receipt containing the exact `reads` and `writes` resources granted to that worker. After the worker opens or updates its PR, `orchid-autonomous-validation.yml` retrieves the latest Swarm lease receipt, enumerates the PR's actual changed files, and invokes `scripts/oc_swarm_write_set_verifier.py` before the normal exact-head test suite.

The verifier maps changed paths back to semantic resources and requires every runtime/configuration write to be covered by the worker's **write** lease. A read claim never authorizes a write. Examples:

- a `literature` worker changing `app/literature_extraction/...` passes;
- the same worker changing an Atlas runtime module fails;
- changing `.github/workflows/...` requires `control-plane`;
- a migration requires `database-schema` plus any identifiable scientific/domain resource;
- globally shared dependency files such as `requirements.txt` require `repo-global`;
- unknown runtime/configuration paths fail closed unless the worker held an explicit `repo-global` write or the conservative `lane-*` fallback lock;
- ancillary tests and documentation do not independently expand runtime authority.

A failed write-set verification makes the exact-head validation fail, so the existing integration supervisor cannot classify that head as green and merge it. This turns resource locking from an advisory scheduler heuristic into an enforceable integration contract.

Legacy or manually-created PRs that have no Swarm resource-lease receipt are not retroactively blocked; v3 enforcement applies to work actually dispatched by the swarm.

## Architecture

1. **Portfolio snapshot** — read open issues and open integration PRs.
2. **Canonical eligibility** — reuse `oc_portfolio_scheduler.py` for priority, durable-PR suppression, blocked states, repair state and owner gates.
3. **Resource classification** — `oc_swarm_resource_locks.py` derives explicit or inferred read/write claims.
4. **Active-lock reconstruction** — every existing `oc-running` issue contributes its resource claims before new work is selected.
5. **Resource-aware planning** — process the canonical ranked queue in order and admit only candidates whose claims do not conflict.
6. **Bounded fan-out** — convert up to 12 selected tasks into a GitHub Actions matrix; default eight.
7. **Lease acquisition** — mark only still-eligible selected issues `oc-running` immediately before launch and publish their claims in the issue receipt.
8. **Parallel implementation** — invoke one existing reusable completion lane per leased issue.
9. **Post-build write-set verification** — compare actual changed files with the durable lease before exact-head validation can become green.
10. **Independent validation/integration** — the existing continuous-completion supervisor remains responsible for exact-head validation and integration into `oc-autonomous-integration`.
11. **Protected boundary** — main/production/scientific-authority decisions remain outside the swarm.

## Defense in depth

Swarm v3 does not assume file-path classification is perfect. It combines semantic resource locking with isolated worker branches, conservative fallback locks for unknown work, exact-head CI, mergeability checks, durable PR suppression and the existing independent integration supervisor. Known resource drift is rejected; unknown runtime drift is rejected unless the worker held a deliberately broad fallback authority.

## Activation

The workflow is intentionally introduced on `oc-autonomous-integration` first. Making it the primary scheduled dispatcher requires normal governed promotion of this control-plane change to the repository default branch after exact-head validation. Until then it can be reviewed and validated without silently changing production orchestration.
