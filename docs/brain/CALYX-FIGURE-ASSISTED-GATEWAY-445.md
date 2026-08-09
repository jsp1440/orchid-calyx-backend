# CALYX BUILD-FIG-301 — assisted scientific figure gateway

Date: 2026-08-08
Issue: #445 / parent #434
Status: implementation candidate; executable CI currently blocked by repository-wide hosted-runner incident #481.

## Objective

Operationalize the existing FigureLabs subscription through a safe, provider-neutral assisted workflow without storing credentials, scraping a private service, bypassing access controls, or granting autonomous scientific publication authority.

Lifecycle:

`evidence-bound figure brief → manual provider interaction/export → bounded SVG/PPTX/PNG import → provenance + semantic-hotspot candidate → scientific/licensing review`

## Implemented contracts

`runtime/figure_assisted_gateway.py` provides:

- deterministic immutable figure briefs with SHA-256 identity;
- project, purpose, required-label, evidence-source, citation, license, provider-hint and output-format metadata;
- explicit maximum estimated cost of $25 per brief;
- allowed source/license policy;
- bounded asset size of 25 MiB;
- SVG, PPTX and PNG format/signature validation;
- active-content rejection for imported SVG (`script`, JavaScript/event-handler surfaces);
- creator, attribution, license, source URI, checksum and exact byte-length preservation;
- deterministic semantic-hotspot candidates bound to evidence URIs;
- exact import replay idempotency and immutable conflict rejection;
- checksum duplicate tracking without overwriting prior assets;
- deterministic readiness with mandatory scientific and licensing review blockers.

The default fixture is an orchid root/velamen scientific plate with required labels for root tip, velamen, exodermis, passage cells, cortex, endodermis and stele.

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
- `GET /briefs/{brief_id}/readiness` — inspect review-only state and blockers.

The router is mounted through the existing live Mission Control router.

## Review and authority boundary

Every imported figure remains a candidate. Readiness always preserves:

- `ready_for_publication=false`;
- `publication_authorized=false`;
- `production_graph_mutation_authorized=false`;
- scientific review required;
- licensing review required.

This implementation does not approve scientific claims or licensing decisions. It does not write to the production Knowledge Graph.

## Validation design

Dedicated workflow:

`.github/workflows/calyx-figure-assisted-gateway-445.yml`

Tests cover:

- deterministic velamen brief identity;
- cost/license guards;
- evidence/provenance/hotspot preservation;
- exact replay idempotency;
- immutable conflicting replay rejection;
- SVG active-content rejection;
- PNG/PPTX signature validation;
- protected Mission Control access;
- Base64 import rejection;
- permanent non-authority and credential-free assertions;
- Ruff and diff hygiene.

## Validation blocker

Canonical repository incident #481 currently causes GitHub-hosted jobs to fail before step 1 with `steps=null`, including zero-dependency smoke workflows on both standard Ubuntu and `ubuntu-slim`. Therefore no no-step run may be represented as a compile/test failure or as a pass.

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
