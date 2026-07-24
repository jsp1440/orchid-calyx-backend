# CALYX-001 — Architecture Ownership Audit

## Purpose

This audit defines how the Calyx graduate-research acquisition and scientific-reasoning program fits into the existing Orchid Continuum architecture. It is intentionally documentation-only. It introduces no migrations, production runtime changes, new identity system, duplicate graph, or parallel scientific object model.

## Architectural decision

Calyx is an orchid-focused literature acquisition and reasoning program layered over existing canonical services. It is not a separate repository platform and does not own taxonomy, documents, evidence, assertions, relationships, publication transactions, knowledge objects, governance, integrity audits, user identity, or research workspaces.

## Canonical ownership matrix

| Capability | Canonical owner | Calyx role | Prohibited duplication |
|---|---|---|---|
| Source discovery and acquisition | Harvester V2 and source plugins | Define orchid-focused source configurations and bounded acquisition jobs | Independent crawler framework |
| BHL literature retrieval | BUILD-103 BHL plugin | Supply query plans and consume normalized records | New BHL client or storage model |
| Document registration and parsing | Existing document-intelligence pipeline | Request parsing and reference parsed spans | Separate document repository |
| Evidence creation and provenance | Scientific Kernel Evidence Engine | Transform reviewed source spans into evidence candidates | New evidence schema or identifier |
| Assertions | Scientific Kernel Assertion Engine | Propose evidence-backed assertions | Free-floating untraceable claims |
| Relationships | Scientific Kernel Relationship Engine | Propose reviewed scientific relationships | Parallel relationship graph |
| Atomic publication | Publication and transaction engine | Submit reviewed manifests | Direct graph writes outside publication boundaries |
| Curated synthesis | Knowledge Object Engine | Produce reviewable orchid-focused syntheses | Separate knowledge-object format |
| Query and retrieval | Scientific Query Engine | Use canonical query contracts | Independent search API over duplicate data |
| Events and orchestration | Scientific Event Bus and Runtime | Emit and consume canonical lifecycle events | Private event taxonomy or orchestration stack |
| Policy and review gates | Governance Engine | Request decisions and honor review requirements | Bypassing policy evaluation |
| Integrity validation | Integrity and Audit Engine | Trigger audits and surface findings | Untracked quality scoring |
| Taxonomy | Existing Orchid Continuum taxonomy backbone | Resolve literature names to canonical taxon concepts with uncertainty retained | New master taxonomy |
| Research workspace | Research Station | Present projects, notes, saved searches, and references to owners | Duplicate users, projects, documents, taxa, or evidence |

## Current capability inventory

The repository already contains the principal architectural building blocks needed for a bounded Calyx pilot:

1. Harvester V2 foundation and source-plugin contracts.
2. GBIF, iNaturalist, and BHL acquisition plugins.
3. Existing document-intelligence and scientific-interpretation work.
4. Candidate-knowledge, evidence-aggregation, and reconciliation services.
5. Atomic publication lifecycle and operational-readiness validation.
6. Scientific Kernel objects for evidence, assertions, relationships, publications, queries, knowledge objects, events, runtime operations, governance, and integrity audits.
7. A draft persistent Research Station backend that must be refreshed against current `main` before it can be considered mergeable.
8. Phase II Brain architecture planning that preserves canonical ownership boundaries rather than replacing them.

## Conflict and duplication register

| Proposed concept in the Calyx report | Conflict risk | Required treatment |
|---|---|---|
| General-purpose research repository | Duplicates document and Research Station ownership | Reject; use canonical document records plus workspace references |
| Separate knowledge graph | Duplicates the Orchid Continuum graph and Kernel relationship model | Reject; publish through canonical relationships and publication manifests |
| New scientific object identifiers | Conflicts with OCIDs | Reject; use Kernel OCIDs |
| Autonomous claim generation | Risks unsupported or unattributed assertions | Require source-span provenance, evidence linkage, review, and policy approval |
| Full-text redistribution | Rights and licence risk | Store and expose only as allowed by source rights; otherwise retain metadata, links, hashes, and permitted excerpts |
| Direct model output as fact | Conflicts with evidence-first architecture | Treat outputs as candidates pending review |
| Independent user/project system | Duplicates Research Station and Calyx ownership boundaries | Reject |
| Bulk ingestion before source verification | Creates rights, quality, and maintenance debt | Reject; begin with bounded verified sources |
| Direct publication to graph | Bypasses transaction, governance, and integrity controls | Reject |

## Source-channel shortlist for the pilot

### Approved existing source

- Biodiversity Heritage Library through the existing BUILD-103 plugin.

### One additional dissertation or thesis metadata source

The second source must be selected only after verifying:

- current API or export availability;
- lawful automated access;
- metadata and full-text licensing distinctions;
- stable identifiers and source URLs;
- rate limits and authentication requirements;
- the ability to preserve institutional and author attribution;
- a workable orchid-focused query strategy.

No specific external dissertation source is authorized by this audit. Selection requires a separate current-source verification task.

## Bounded pilot specification

### Scientific scope

- Orchids only.
- One tightly defined research question or taxonomic group.
- BHL plus one independently verified dissertation metadata channel.
- Small enough for complete human review before publication.

### End-to-end flow

1. Define an orchid-focused discovery query and acquisition budget.
2. Acquire source metadata and permitted content through canonical harvesters.
3. Register or reference the canonical document record.
4. Parse content into stable, citable source spans.
5. Produce candidate evidence records retaining exact source attribution and rights state.
6. Propose assertions and relationships only from linked evidence.
7. Route candidates through human review and governance policy evaluation.
8. Run integrity audits on identifiers, provenance, evidence links, rights state, and publication consistency.
9. Commit accepted objects through an atomic publication manifest.
10. Expose the resulting synthesis through a canonical Knowledge Object and Research Station project view.

### Mandatory invariants

- Every scientific claim is traceable to one or more exact source spans.
- Every source retains stable provenance and rights metadata.
- Automated outputs remain candidate records until reviewed.
- Rejected and disputed candidates remain auditable.
- No non-permitted full text is redistributed.
- Taxonomic uncertainty and historical names are preserved rather than silently normalized away.
- Publication occurs only through canonical transaction boundaries.
- No production database changes occur during CALYX-001.

## Follow-on build sequence

1. **CALYX-002 — Current source verification and pilot corpus definition**
   Verify the dissertation channel, choose the bounded scientific question, define records and rights limits, and produce fixtures.

2. **CALYX-003 — Acquisition adapter and canonical document handoff**
   Add only the missing source adapter and connect its normalized output to existing document ownership.

3. **CALYX-004 — Source-span evidence candidate pipeline**
   Create reviewable evidence candidates linked to exact parsed spans and rights metadata.

4. **CALYX-005 — Assertion, relationship, and review workflow integration**
   Map approved candidates into Kernel assertions and relationships through governance-controlled review.

5. **CALYX-006 — Atomic publication and Knowledge Object pilot**
   Publish the reviewed sample through a manifest, run integrity checks, and create a curated synthesis.

6. **CALYX-007 — Research Station presentation**
   Surface the pilot within owner-isolated projects after the Research Station branch is refreshed, validated, and independently merged.

## Acceptance status

- Architecture ownership matrix: complete.
- Current capability inventory: complete at architectural level.
- Conflict and duplication register: complete.
- Source shortlist: BHL approved; second source requires current verification.
- Bounded pilot specification: complete.
- Runtime or database modifications: none.

## Repository dependency note

`BUILD-RS-001` remains a separate draft pull request. CALYX-001 does not merge, modify, or depend on its current branch. Any Research Station integration must first rebase or rebuild that work from the then-current `main`, rerun the full relevant validation matrix, and receive independent review.
