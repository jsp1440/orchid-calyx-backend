# Orchid Continuum Swarm Controller

The Swarm Controller converts the continuously refilling Orchid Continuum portfolio into bounded parallel implementation waves.

## Swarm v2 operating envelope

- hard maximum: 12 implementation workers per wave;
- default requested capacity: 8 workers;
- canonical `oc-queued` portfolio and existing priority policy remain authoritative;
- durable PR suppression, owner gates, repair/backoff and blocked states remain authoritative;
- each worker uses the existing `orchid-completion-lane.yml` contract;
- workers target `oc-autonomous-integration`, never `main`;
- the planner performs no provider call, deployment, merge, scientific publication, taxonomy activation, credential change or production mutation.

## Why resource locks

Swarm v1 conservatively allowed one worker per coarse product lane. That prevented collision storms, but it also meant two unrelated L3 jobs such as literature provenance and image provenance could not run together.

Swarm v2 separates **product lanes** from **resources**. Product lanes remain useful for reporting and fallback safety, while resource claims determine whether work can execute concurrently.

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

## Architecture

1. **Portfolio snapshot** — read open issues and open integration PRs.
2. **Canonical eligibility** — reuse `oc_portfolio_scheduler.py` for priority, durable-PR suppression, blocked states, repair state and owner gates.
3. **Resource classification** — `oc_swarm_resource_locks.py` derives explicit or inferred read/write claims.
4. **Active-lock reconstruction** — every existing `oc-running` issue contributes its resource claims before new work is selected.
5. **Resource-aware planning** — process the canonical ranked queue in order and admit only candidates whose claims do not conflict.
6. **Bounded fan-out** — convert up to 12 selected tasks into a GitHub Actions matrix; default eight.
7. **Lease acquisition** — mark only still-eligible selected issues `oc-running` immediately before launch and publish their claims in the issue receipt.
8. **Parallel implementation** — invoke one existing reusable completion lane per leased issue.
9. **Independent validation/integration** — the existing continuous-completion supervisor remains responsible for exact-head validation and integration into `oc-autonomous-integration`.
10. **Protected boundary** — main/production/scientific-authority decisions remain outside the swarm.

## Important limitation

Resource locking prevents known semantic resource conflicts; it cannot know the exact file write-set of code that has not been generated yet. Therefore the system remains fail-closed for unclassified work and continues to rely on isolated branches, exact-head CI, mergeability checks and independent integration validation as defense in depth.

The next hardening step is **post-build write-set verification**: compare each delivered PR's actual changed files against its declared/inferred resource claim and reject or reclassify any worker that escaped its lease. That provides a measurable enforcement loop rather than trusting pre-build classification alone.

## Activation

The workflow is intentionally introduced on `oc-autonomous-integration` first. Making it the primary scheduled dispatcher requires normal governed promotion of this control-plane change to the repository default branch after exact-head validation. Until then it can be reviewed and validated without silently changing production orchestration.
