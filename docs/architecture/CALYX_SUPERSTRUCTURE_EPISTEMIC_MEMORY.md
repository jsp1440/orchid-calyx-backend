# Calyx Superstructure: Epistemic Memory Contract

Status: implementation slice for #1123.

## Purpose

Calyx may preserve its prior hypotheses, interpretations, conclusions, conflicts, and review context as durable institutional memory so later missions can reuse what the Orchid Continuum has already reasoned about.

This capability is deliberately **not** a self-authorizing truth loop. A prior Calyx conclusion is prior reasoning context, not new source evidence. Recalling it cannot increase the evidentiary weight of the underlying claim merely because the system has seen or stated the claim before.

## Canonical boundary

The existing Brain, reasoning ledger, evidence/provenance architecture, candidate-knowledge lifecycle, controlled publication gate, and authoritative Knowledge Graph remain canonical for their existing responsibilities.

The epistemic-memory layer is a deterministic projection over durable reasoning-ledger revisions. It does not write directly to `oc_graph` and does not create a competing scientific truth store.

A projected machine-memory node always carries these invariants:

- `authority = non_authoritative`;
- `canonical_knowledge = false`;
- `source_evidence = false`;
- `can_be_cited_as_source_evidence = false`;
- `can_trigger_publication = false`;
- `requires_controlled_publication_gate = true`;
- scientific inference classes require independent evidence for any new claim.

Review or approval of a reasoning ledger does not alter those flags. Promotion to canonical published knowledge continues only through the existing governed publication path.

## Why this is still learning

The system can improve without retraining a foundation model or corrupting its evidence base. Later missions may retrieve prior machine memories to:

- avoid repeating an already explored hypothesis;
- recover useful interpretations and unresolved questions;
- find earlier counterevidence or conflicts;
- compare a new result with earlier conclusions;
- prioritize knowledge gaps;
- re-open an earlier interpretation when new independent evidence appears;
- learn which reasoning paths were productive or unproductive.

This is institutional/epistemic learning rather than model-weight training.

## Grounding states

Every projected reasoning entry has an explicit grounding state:

- `direct` — the entry itself carries canonical provenance to an upstream source identity;
- `transitive` — the entry references another reasoning entry that ultimately has source provenance;
- `ungrounded` — no independent source lineage is reachable.

Grounding traversal is cycle-safe. Two or more machine memories that cite only each other remain ungrounded. Circular recall cannot manufacture evidence.

## Reasoning graph

The projection gives every durable ledger revision and entry a stable graph identity.

Representative node classes include:

- reasoning-ledger revision;
- hypothesis;
- conclusion;
- support;
- counterevidence;
- conflict;
- assumption;
- review decision;
- memory reference;
- operation and intermediate artifact.

Reference edges preserve reasoning relationships such as:

- `supports`;
- `counters`;
- `conflicts_with`;
- `assumes`;
- `derived_from`;
- `references_memory`;
- `reviews`.

The projection also retains provenance, confidence, uncertainty rationale, unresolved assumptions, conflict state, tags, attributes, content hashes, ledger revision, and project identity.

## Project memory corpus

A project-level corpus assembles recallable memory across all reasoning ledgers visible to the authenticated project owner. The corpus is deterministic and receives a stable fingerprint derived from its member ledger projections.

The corpus is a retrieval surface, not evidence. Each memory retains its original ledger and entry identity and the same non-authoritative publication boundary.

Initial read APIs:

- `GET /api/reasoning-ledgers/{ledger_id}/epistemic-memory`
- `GET /api/research/projects/{project_id}/epistemic-memory`

Both reuse the existing owner/authentication and project isolation boundaries.

## Anti-self-contamination rule

A later Calyx mission may say, in effect:

> Prior reasoning proposed hypothesis H with confidence 0.71, grounded transitively in evidence E1 and E2, while conflict C remained unresolved.

It may not say:

> H is now better supported because Calyx previously concluded H.

If a new mission wants to advance H, it must retrieve the independent evidence beneath H, seek new evidence where appropriate, preserve counterevidence, and pass the same candidate/review/publication gates as any other scientific assertion.

## Next superstructure planes

This slice establishes Plane A of #1123. Subsequent bounded work should add, in order:

1. Experience Ledger: mission outcome, validation, failure, recovery, and reusable lessons.
2. Capability/Agent Registry: model/tool skills, health, authority, cost, restrictions, and historical performance.
3. Meta-Orchestrator: consequence-aware team assembly, model routing, recovery, and governed stopping conditions.
4. Independent adversarial verification integrated with Check Calyx / Verification Workbench.
5. Governed knowledge-gap discovery and hypothesis proposal.

No later plane may bypass the epistemic distinction implemented here.
