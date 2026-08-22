# Calyx Superstructure: Experience Ledger Contract

Status: implementation slice for #1125, Plane B of #1123.

## Purpose

The Experience Ledger gives the Orchid Continuum durable institutional memory of **how autonomous work actually went**: objective, role composition, dependencies, attempts, execution receipts, evidence anchors, blockers, escalations, recoveries, terminal outcomes, and bounded lessons.

It is complementary to the epistemic scientific-memory layer:

- epistemic memory remembers what Calyx hypothesized, interpreted, concluded, contested, or left unresolved;
- experience memory remembers which governed execution patterns succeeded, failed, recovered, escalated, or terminated as no-ops.

Together they allow future planning to use prior scientific reasoning and prior operational experience without turning either into self-authorizing truth.

## Canonical boundary

The existing durable orchestration tables and authoritative execution receipts remain canonical for execution state. Experience memory is a deterministic projection over those records. It does not create a competing scheduler, task database, authority system, or truth store.

Every Experience Ledger carries these restrictions:

- it may inform future planning;
- it may not rewrite policy;
- it may not expand permissions;
- it may not trigger production action by itself;
- it is not scientific source evidence;
- it stores no private chain-of-thought.

## Memory retained

For each program, the projection retains:

- program identity, title, objective, lifecycle state and timestamps;
- job identity, role, repository, branch, mutation flag, work fingerprint and orchestrator identity;
- attempt and retry counts;
- terminal outcome, blocker, explicit human action and recovery-after-retry state;
- dependency topology;
- receipt type, executor identity, input/output checksums, evidence URIs and blocker code;
- executor-output **keys and checksum only**, not the full generated output body;
- aggregate outcome counts, participating executors and validation evidence URIs;
- deterministic experience fingerprint.

This retention policy provides useful lineage while reducing accidental long-term storage of sensitive, large, or irrelevant generated content.

## Lesson candidates

The first version recognizes bounded descriptive patterns:

- `successful_execution_pattern`;
- `recovery_after_retry`;
- `persistent_blocker`;
- `human_escalation_required`;
- `dependency_failure_propagation`;
- `no_op_pattern`.

A lesson candidate records the observed pattern with evidence references and applicability bounds such as role, repository, and mutation class.

`confidence = 1.0` means only that the recorded execution pattern itself was directly observed in durable execution state. It is **not** a prediction that the same action will succeed again. Predictive confidence must be learned later from aggregated repeated experience.

Lesson candidates therefore carry explicit guards:

- `authority = non_authoritative_lesson_candidate`;
- `may_inform_planning = true`;
- `may_rewrite_policy = false`;
- `may_expand_permissions = false`;
- `may_trigger_deployment = false`;
- `may_publish_scientific_claim = false`.

## Initial API

Owner-authenticated read surface:

`GET /programs/{program_id}/experience-memory`

The loader reuses the existing program snapshot lookup as the canonical ownership boundary before projecting raw job/dependency state.

## Learning model

A future meta-orchestrator can retrieve relevant experience before planning. For example:

1. objective arrives;
2. orchestrator identifies task classes and consequence level;
3. relevant epistemic memories and execution experiences are retrieved;
4. planner sees prior successful patterns, blockers, recovery paths, no-op signals, and escalation boundaries;
5. planner proposes the minimum sufficient agent team and execution plan;
6. current policy/permissions are checked independently;
7. after execution, a new Experience Ledger state becomes available for future runs.

This is institutional learning without recursive privilege escalation.

## Relationship to Capability Registry

The repository already has an `AuthoritativeExecutorRegistry`; Plane C must extend rather than replace it.

Experience Ledger provides the empirical signals needed for richer capability profiles: success/failure counts by task class, retry pressure, blocker classes, no-op frequency, evidence quality, and recovery history. Static executor authority remains separate from empirical performance.

## Next bounded work

After this slice is validated and integrated:

1. add a cross-program Experience Corpus / retrieval index;
2. derive empirical capability/performance profiles over the existing executor registry;
3. implement consequence-aware meta-orchestration that retrieves both epistemic and experience memory;
4. integrate independent adversarial verification before high-consequence completion;
5. only then enable governed knowledge-gap discovery and hypothesis proposal.
