# CALYX BUILD-FIG-301 — assisted scientific figure gateway

Date: 2026-08-08
Issue: #445 / parent #434
Status: implementation candidate; executable CI currently blocked by repository-wide hosted-runner incident #481.

## Objective

Operationalize the existing FigureLabs subscription through a safe, provider-neutral assisted workflow without storing credentials, scraping a private service, bypassing access controls, or granting autonomous scientific publication authority.

Lifecycle:

`evidence-bound figure brief → manual provider interaction/export → bounded SVG/PPTX/PNG import → BUILD-BRAIN-111 artifact provenance → semantic-hotspot candidate → scientific/licensing review`

## Implemented contracts

`runtime/figure_assisted_gateway.py` provides:

- deterministic immutable figure briefs with SHA-256 identity;
- project, purpose, canonical required labels, evidence source/citation/license, provider hint and requested output formats;
- explicit maximum estimated cost of $25 per brief;
- allowed source/license policy;
- bounded asset size of 25 MiB;
- imported format must be explicitly requested by the brief;
- PNG signature validation;
- PPTX ZIP structure validation requiring `[Content_Types].xml` and `ppt/presentation.xml`, with path-traversal, member-count and uncompressed-expansion limits;
- SVG active/external-content rejection for scripts, JavaScript/event handlers, DOCTYPE/entities and external HTTP(S) hrefs;
- creator, attribution, license, source URI, checksum and exact byte-length preservation;
- deterministic semantic-hotspot candidates bound to evidence URIs;
- exact import replay idempotency and immutable conflict rejection;
- deterministic readiness with exact missing output formats and mandatory scientific/licensing review blockers.

The default fixture is an orchid root/velamen scientific plate with required labels for root tip, velamen, exodermis, passage cells, cortex, endodermis and stele.

## Authoritative artifact registry integration

The initial implementation draft contained a local checksum/duplicate map. That was removed during architecture review because BUILD-BRAIN-111 is already the repository authority for artifact identity and duplicate-content evidence.

Imported assets now register through `ImmutableArtifactRegistry` using `ArtifactRegistration` with:

- exact asset content/checksum/media type;
- source URI;
- BUILD-FIG-301 producer assignment identity;
- license;
- source-evidence and semantic-hotspot evidence URIs;
- brief digest, creator, attribution and review-state metadata.

`require_evidence()` is applied after registration. Cross-brief duplicate-content signals come from BUILD-BRAIN-111 rather than a parallel registry.

## Assisted-provider boundary

The generated brief package explicitly states:

- `mode=assisted`;
- `provider_network_call_authorized=false`;
- `credential_storage_authorized=false`;
- `operator_exports_asset_manually=true`.

No provider HTTP client, browser automation, password storage, cookie storage, CAPTCHA bypass, private endpoint reverse engineering, or hidden credential mechanism is present in this slice.

## Protected Mission Control API

`app/routers/figure_assisted_gateway.py` exposes owner/API-key protected routes under:

`/brain/mission-control/figures`

- `GET /fixtures/orchid-root-velamen` — deterministic evidence-bound example brief;
- `POST /briefs` — create a bounded immutable candidate brief;
- `GET /briefs/{brief_id}` — retrieve exact brief package/digest;
- `POST /briefs/{brief_id}/imports` — import an operator-exported SVG/PPTX/PNG candidate with provenance;
- `GET /briefs/{brief_id}/readiness` — inspect review-only state, missing formats and blockers.

The router is mounted through the existing live Mission Control router.

## Review and authority boundary

Every imported figure remains a candidate. Readiness always preserves:

- required review classes `scientific` and `licensing`;
- `ready_for_publication=false`;
- `publication_authorized=false`;
- `production_graph_mutation_authorized=false`.

This implementation does not approve scientific claims or licensing decisions. It does not write to the production Knowledge Graph.

## Validation design

Dedicated workflow:

`.github/workflows/calyx-figure-assisted-gateway-445.yml`

Tests cover:

- deterministic velamen brief identity;
- cost/license and canonical-format guards;
- evidence/provenance/hotspot preservation;
- BUILD-BRAIN-111 artifact-registry integration;
- duplicate-content signal across different briefs;
- exact replay idempotency;
- immutable conflicting replay rejection;
- SVG active/external-content rejection;
- PNG/PPTX signature and PPTX structure/traversal validation;
- requested-format enforcement and missing-format readiness;
- protected Mission Control access;
- invalid Base64 rejection;
- permanent non-authority and credential-free assertions;
- BUILD-BRAIN-111 regression tests;
- Ruff and diff hygiene.

## Validation blocker

The first exact-head PR #715 workflow cycle on head `b09b54f72d6251cd86e2593cd423009ce5bd306e` reproduced canonical incident #481. `CALYX Figure Assisted Gateway 445` run `31288922550`, job `93182662893`, failed before step 1 with `steps=null`. BUILD-088E, Workflow Governance, Supervised Pilot and Autonomy Deployment on the same head also terminated as infrastructure failures.

Subsequent implementation heads intentionally add ingestion and BUILD-BRAIN-111 integration hardening, so the older no-step run is not represented as validation evidence for the current code.

Canonical repository incident #481 also includes zero-dependency standard Ubuntu and `ubuntu-slim` smoke failures before step 1. Therefore no no-step run may be represented as a compile/test failure or as a pass.

This branch must remain draft/unmerged until the exact unchanged head receives executable CI and the dedicated Figure Assisted Gateway workflow passes.

## Explicit non-actions

This slice does not:

- store or request a FigureLabs password/token;
- scrape cookies or browser state;
- bypass CAPTCHA or access controls;
- reverse engineer private provider endpoints;
- automatically send a figure brief to a provider;
- automatically publish generated figures;
- approve scientific or licensing review;
- mutate production Knowledge Graph data;
- deploy;
- merge.
