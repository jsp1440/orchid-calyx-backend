# CALYX-BRAIN-003 Implementation and Architecture Impact Statement

## Operational audit

BUILD-078 is the older candidate-oriented gate. BUILD-088B through BUILD-088D is the operational canonical system: immutable policy and publication registries, authority decisions, atomic graph transaction manifests, graph-version history, provenance links, duplicate suppression, lifecycle correction, retraction, and rollback records.

The canonical write entry point is KnowledgePublicationService.submit/evaluate followed by ControlledGraphPublicationService.publish. The latter delegates to PostgresControlledGraphRepository, which alone prepares ordered operations and writes canonical oc_graph nodes or edges. CALYX-BRAIN-003 contains no graph SQL.

Reasoning Ledger owns immutable reasoning revisions and exact-version human approvals. Literature Intelligence owns evidence and source hashes. Research Station owns project authorization. reasoning_publication owns only the ledger-to-gate publication artifact and attempts. oc_knowledge_publication remains authoritative for publication policy, authorization, graph transactions, publication lifecycle, retraction, and rollback.

## Eligibility

Publication fails closed unless the authenticated owner can load the current, non-archived project ledger; requested version and review-content hash exactly match; one current approved decision exists; the canonical ledger gate reports no unresolved/deferred conflict, missing conclusion, low confidence, or stale approval; literature references and hashes still resolve; exactly one conclusion describes a supported operation; subject/object identities are explicit; evidence and source hashes are present; no private-reasoning keys occur; no outreach/marketing tag or source occurs; and a canonical scientific assertion plus active publication-policy binding is supplied by trusted ledger content.

The existing BUILD-088 gate performs final assertion, eligibility, policy, taxonomy, provenance, relationship, duplicate, conflict, and graph constraints. Failure is never downgraded or partially published.

## Artifact and deterministic identity

The immutable snapshot contains artifact ID/hash, ledger/version/review hash, approval/reviewer/timestamps, server-derived actor/owner/project, canonical graph operation, evidence and counterevidence, literature IDs and source hashes, inference rule metadata, confidence, concise rationale, provenance, candidate/inference lineage, canonical assertion and policy binding, lifecycle result, and canonical publication/graph result.

The SHA-256 identity binds ledger ID, exact version, exact review hash, approval ID, normalized operation, subject, predicate, object/literal, owner, and project. A namespace UUID derived from that digest is the stable artifact ID. A unique database constraint and row lock serialize duplicates. The canonical gate separately uses the digest as its idempotency key. Identical replay returns the published artifact and graph result without a second gate call or graph write.

## Sequence

    authenticated owner
      -> publication adapter
      -> current owned Reasoning Ledger
      -> Research Station and Literature revalidation
      -> exact approval and eligibility validation
      -> deterministic publication artifact
      -> BUILD-088 publication and graph gate
      -> atomic canonical scientific graph transaction
      -> canonical IDs and auditable artifact result

## API and authorization

- POST /api/reasoning-ledgers/{ledger_id}/publish
- GET /api/reasoning-ledgers/{ledger_id}/publications

The request may set only expected version, expected review hash, and an optional concise note. Owner, tenant, actor, reviewer, approval, provenance, status, and graph identifiers are derived from persisted state. Existing authentication, owner isolation, project ownership/archive checks, and canonical gate authority are reused. Extra request fields are rejected.

## Lifecycle, audit, and failure

Adapter lifecycle terms are prepared, validated, submitted, published, rejected, blocked, superseded, and retracted. Each gate attempt is append-only. Gate rejection remains stored with its reason. Published identity and snapshot fields cannot be changed. Supersession, retraction, canonical graph history, and rollback remain BUILD-088D responsibilities and never erase provenance.

## Migration and rollback

Dependency order is 087B, 088B, 088C, 088D, 101, 103, 104, then 105. Migration 105 creates only reasoning_publication.publication_artifacts and publication_attempts, their indexes, uniqueness constraints, foreign keys, and immutability protections. Reapplication is supported. The explicit pre-production rollback drops only reasoning_publication; it does not touch ledger, project, Brain, publication-gate, or graph schemas.

## Governance boundaries

Inference is not canonical knowledge. Reasoning Ledger approval is necessary but does not itself write to the graph. Publication occurs only through the canonical Knowledge Graph gate. Exact version and exact review hash are revalidated at publication time. Private chain-of-thought is neither requested nor persisted. Only concise externally reviewable rationale is stored. Outreach and marketing data cannot enter the scientific graph through this adapter.

## Production prerequisites and limitations

- Merge PR #172, then PR #188, then retarget/rebase this stacked PR.
- Obtain successful disposable PostgreSQL 16 validation and stage the complete migration chain.
- Configure the existing database, authentication, active BUILD-088 policy, canonical assertion, eligibility, taxonomy, evidence, and provenance records.
- Resolve the GitHub Actions runner-startup condition seen on the dependency branch.
- The adapter publishes one unambiguous conclusion per artifact; multi-operation ledger publication requires a later governed design.
- Reviewer/submitter separation follows existing governance; stronger separation requires a policy-layer change.

No production migration or deployment was performed.

## Next dependency-ordered build

After staged operational validation, add governed post-publication monitoring that links BUILD-088D re-evaluation, supersession, withdrawal, and retraction events back to the originating immutable ledger artifact without changing historical reasoning or graph provenance.
