# Orchid Continuum Swarm Controller

The Swarm Controller converts the existing continuously refilling Orchid Continuum portfolio into bounded parallel implementation waves.

## Initial operating envelope

- hard maximum: 8 implementation workers per wave;
- default requested capacity: 5 workers;
- canonical `oc-queued` portfolio and existing priority policy remain authoritative;
- durable PR suppression, repair reservation, owner gates, runtime backoff and blocked states remain authoritative;
- each worker uses the existing `orchid-completion-lane.yml` contract;
- workers target `oc-autonomous-integration`, never `main`;
- the planner performs no provider call, deployment, merge, scientific publication, taxonomy activation, credential change or production mutation.

The default of five is deliberate: the existing portfolio scheduler has five canonical product lanes and normally permits one active implementation per lane, preventing the first swarm release from creating a merge-conflict storm. The controller accepts up to eight slots so future explicit sub-lane locking can widen parallelism without redesigning the launch contract.

## Architecture

1. **Portfolio snapshot** — read open issues and open integration PRs.
2. **Deterministic planning** — reuse `oc_portfolio_scheduler.py` for priority, fairness, durable-PR suppression and lane safety.
3. **Bounded fan-out** — convert selected issues into a GitHub Actions matrix.
4. **Lease acquisition** — mark only still-eligible selected issues `oc-running` immediately before launch.
5. **Parallel implementation** — invoke one existing reusable completion lane per leased issue.
6. **Independent validation/integration** — the existing continuous-completion supervisor remains responsible for exact-head validation and integration into `oc-autonomous-integration`.
7. **Protected boundary** — main/production/scientific-authority decisions remain outside the swarm.

## Activation

The workflow is intentionally introduced on `oc-autonomous-integration` first. Scheduling or making it the primary dispatcher requires the normal governed promotion of this control-plane change to the repository default branch after exact-head validation. Until then it can be reviewed and validated without silently changing production orchestration.

## Scaling beyond five implementation workers

The next scale step is explicit sub-lane resource locking: tasks declare durable resource keys (for example taxonomy-read, literature, atlas-ui, research-station, calyx-reasoning) and the planner may run multiple tasks from the same broad product lane only when their write sets do not overlap. The hard cap of eight is already present so that widening is bounded rather than unrestrained.
