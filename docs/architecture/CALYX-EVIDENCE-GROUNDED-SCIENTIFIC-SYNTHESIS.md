# Calyx Evidence-Grounded Scientific Synthesis

## Mission

Calyx must be able to answer a scientific question by discovering and verifying literature, extracting source-bound evidence, reasoning across studies, and producing audience-appropriate scientific prose without inventing references or silently converting inference into fact.

The authoring layer is downstream of evidence and interpretation. It may change wording and organization; it may not create unsupported scientific content.

## Governing invariants

1. Search results are candidates, not evidence.
2. A source cited in a publication artifact must be bibliographically verified against an authoritative registry or publisher record, with nonblank provider and verification identifier.
3. Evidence must retain immutable source revision identity, a usable locator, source content hash, and excerpt hash; blank revision IDs or empty/blank-only locators block readiness.
4. Direct scientific claims require primary experimental support.
5. Commercial claims, expert practice, observations, controlled experiments, direct tracer studies, and mechanistic inference remain distinct evidence classes.
6. Scientific prose must carry claim-level grounding; every scientific sentence must resolve to one or more synthesis claims.
7. Inference must be explicit and include a rationale.
8. Conflicting evidence is retained rather than averaged away.
9. Synthesis validation never publishes Knowledge Graph truth. Existing review/publication governance remains authoritative.
10. Identical inputs produce a deterministic validation fingerprint.

## CALYX-SYN-001 implemented slice

This build establishes the first executable grounding contract:

- `app/scientific_synthesis/models.py`
  - bibliographic verification state
  - evidence classes
  - immutable evidence-anchor references
  - evidence-matrix rows
  - direct/synthesis/inference claims
  - sentence-level article grounding
- `app/scientific_synthesis/service.py`
  - deterministic validation fingerprint
  - verification gate for article bibliography
  - provider/identifier provenance requirement for verified bibliography records
  - anchor identity, source revision, usable locator, source hash, and excerpt-hash checks
  - primary-evidence requirement for direct claims
  - explicit inference-rationale requirement
  - sentence-to-claim and claim-to-evidence integrity checks
  - bibliography completeness check
  - publication readiness manifest
- `app/scientific_synthesis/routes.py`
  - authenticated API mounted below Scientific Interpretation
  - `POST /api/scientific-interpretation/synthesis/validate`
  - `GET /api/scientific-interpretation/synthesis/health`
- regressions for verified primary evidence, unsupported verified-state blocking, incomplete-anchor blocking, unverified-source blocking, ungrounded prose blocking, commercial-only direct-claim blocking, inference labeling, deterministic fingerprints, and route mounting.

The validator deliberately does **not** generate prose and does **not** search the web. It is the safety boundary that later discovery and authoring components must satisfy.

## Dependency-ordered implementation program

### CALYX-SYN-002 — Canonical source binding and anchor integrity

Connect synthesis evidence rows to existing Document Intelligence / Literature Intelligence canonical source identities. Repair and enforce exact evidence-span hashing so normalized retrieval text cannot be paired with a locator/hash from different source content.

Acceptance: every synthesis evidence row can be dereferenced to the exact immutable source passage/table/figure used to support it.

### CALYX-SYN-003 — Literature discovery and bibliographic verification

Add provider adapters behind a common discovery interface. Candidate providers include Crossref, OpenAlex, PubMed where applicable, BHL/botanical sources, and publisher DOI records. Verification must be provider-attributed and deterministic; model memory is never a verification provider.

Acceptance: given a research question, Calyx returns deduplicated candidate citations and separates verified records from unresolved candidates.

### CALYX-SYN-004 — Evidence matrix extraction

Map verified papers and existing extracted claims/evidence into study-level matrix rows containing taxon, intervention/exposure, comparator, outcome, method, sample size, result, uncertainty, limitations, and exact source anchors.

Acceptance: no matrix field containing a scientific result exists without source-bound evidence.

### CALYX-SYN-005 — Governed cross-study synthesis

Orchestrate Candidate Knowledge -> Evidence Aggregation -> Scientific Interpretation into synthesis claims while retaining contradictory evidence, uncertainty, scope, taxonomic ambiguity, and alternative explanations.

Acceptance: direct statements, cross-study synthesis, and inference are machine-distinguishable and traceable.

### CALYX-SYN-006 — Grounded scientific authoring

Add an authoring adapter that receives only validated synthesis objects plus audience/style constraints. It generates sentence objects carrying claim IDs rather than free-standing prose.

Acceptance: deleting the supporting claim/evidence for a scientific sentence causes article validation to fail.

### CALYX-SYN-007 — Citation and quantitative audit

Validate DOI/title/author consistency, bibliography completeness, numerical claims, units, quoted text limits, contradiction coverage, and source-to-sentence support before export.

Acceptance: an article cannot reach `publication_ready=true` with an unresolved or unverified scientific citation.

### CALYX-SYN-008 — Figure evidence briefs

Generate figure briefs whose anatomical structures, quantitative comparisons, captions, and uncertainty annotations are grounded in synthesis evidence. Figure generation remains a downstream presentation task.

### CALYX-SYN-009 — Research-to-article mission orchestration

Expose the full mission:

`question -> discovery -> verification -> acquisition -> extraction -> evidence matrix -> synthesis -> authoring -> audit -> human review/export`

No autonomous path may bypass existing publication governance.

## Canonical benchmark

The first end-to-end benchmark is:

> Do orchids respond to foliar feeding, and is foliar fertilization horticulturally useful despite the thick leaf cuticle?

The benchmark must distinguish direct foliar absorption from runoff/root uptake, growth response, biostimulant effects, commercial/expert claims, and mechanistic inference. It must verify every cited primary paper and produce an evidence matrix, evidence-graded conclusions, a newsletter article, references, figure briefs, and sentence-level provenance.

## Non-goals

- replacing the Knowledge Graph publication controls
- treating vendor or grower testimony as primary experimental evidence
- allowing an LLM to create bibliography entries from memory
- hiding disagreement or uncertainty to make prose read more smoothly
- using the authoring layer as a competing reasoning store
