# Priority Batch — BUILD-ATLAS-405 through BUILD-INT-953

Status: candidate implementation; draft only.

## Implemented vertical slices

1. **BUILD-ATLAS-405** — evidence-linked temporal layer comparison with explicit candidate status, ordering checks, absolute change, and percent change.
2. **BUILD-RS-502** — governed experiment runs tied to versioned protocol checksums, input artifacts, completion times, and output artifacts.
3. **BUILD-CON-602** — staged inventory import with duplicate-accession rejection, row-level rejection reporting, stable checksums, and no automatic commit.
4. **BUILD-MATRIX-702** — deterministic identification-key generation from character states and candidate taxon branches.
5. **BUILD-VISION-802** — versioned image annotation sets with normalized coordinates, evidence links, duplicate rejection, checksums, and candidate review state.
6. **BUILD-PUB-902** — deterministic citation manifests with source URIs, licenses, access dates, duplicate rejection, and stable checksums.
7. **BUILD-INT-952** — event replay ledger that accepts first delivery, treats exact replay as idempotent, and rejects conflicting payloads.
8. **BUILD-MC-203** — SLA-aware stale-work and blocked-work health summaries for Mission Control.
9. **BUILD-BRAIN-115** — living design-manual generation from ordered Brain object sections, with deterministic checksums and publication disabled.
10. **BUILD-INT-953** — integration-contract readiness assessment with explicit producer, consumer, event type, schema version, evidence, enablement, and blocker reporting.

## Validation coverage

Focused tests cover temporal ordering, layer identity, experiment completion controls, inventory duplicate rejection, deterministic key ordering, annotation image consistency, citation uniqueness, event replay conflict handling, SLA health, design-manual determinism, and integration readiness.

## Safety boundary

These are bounded candidate contracts. They do not import live Earth datasets, execute research experiments, commit collection imports, publish identification keys or annotations, deliver events externally, publish design manuals, enable integrations automatically, merge code, deploy services, or mutate the production Knowledge Graph.
