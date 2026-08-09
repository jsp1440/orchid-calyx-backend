# CALYX-SYN-005 through SYN-009 — Governed Research-to-Article Pipeline

## Mission

Complete the post-acquisition scientific synthesis path so Calyx can turn verified, exact-source-bound evidence into an auditable article and Figure Labs briefs without allowing a writing model to create unsupported science.

## SYN-005 — Reviewed evidence classification and cross-study synthesis

Evidence matrix rows begin conservatively classified. Any upgrade to `CONTROLLED_EXPERIMENT`, `DIRECT_TRACER`, or another stronger design class requires an explicit decision with reviewer identity and rationale.

Cross-study synthesis groups evidence by taxon/outcome and emits `SynthesisClaim` objects. Single reviewed experimental rows may support a direct claim. Multi-source groups produce synthesis claims and retain conflicting evidence IDs when source polarity is mixed, negative, or uncertain.

No inference claim is created automatically.

## SYN-006 — Grounded scientific authoring

The authoring service receives only:

- the research question and presentation constraints
- verified bibliography
- source-bound evidence rows
- synthesis claims

Every scientific sentence in the generated `ArticleDraft` is copied from a synthesis claim and carries that claim ID. Introductory/closing process prose is explicitly non-scientific. Markdown rendering is deterministic and bibliography-limited to sources that support article claims.

The author therefore has permission to organize and render verified conclusions, not to invent new scientific statements.

## SYN-007 — Article grounding and quantitative audit

The existing CALYX-SYN-001 validator remains authoritative for claim/evidence/bibliography grounding. The article audit additionally scans scientific sentences for numerical values and blocks values that are not present in their supporting evidence fields.

Article audit cannot publish Knowledge Graph truth. Passing means the draft is eligible for human editorial review, not automatically published.

## SYN-008 — Figure evidence briefs

Each synthesis claim produces a Figure Labs evidence brief containing:

- the visual claim
- supporting claim IDs
- supporting source IDs
- uncertainty notes
- an explicit instruction not to invent anatomy, measurements, causal mechanisms, taxa, or effect sizes

The brief is an evidence-constrained visualization specification, not an image-generation result.

## SYN-009 — Research-to-article mission

`ResearchToArticleMissionService` runs the governed post-acquisition sequence:

`reviewed classification -> cross-study synthesis -> grounded authoring -> article audit -> figure evidence briefs`

The authenticated runtime endpoint is:

`POST /api/scientific-interpretation/research-article/run`

A successful mission returns:

- classified evidence rows
- traceable synthesis claims
- structured article
- rendered Markdown article
- audit manifest
- Figure Labs briefs
- `human_review_required: true`
- `published: false`

## Full question-to-article boundary

CALYX-SYN-003 now supplies question-driven literature discovery and authoritative DOI verification. Full text still must enter through the governed acquisition/intake/document-intelligence boundary before it can become scientific evidence. This is deliberate: bibliographic discovery does not imply lawful or trustworthy access to a paper's full text.

Accordingly the full system is:

`question -> discovery candidate -> authoritative bibliographic verification -> governed source acquisition/intake -> literature extraction -> exact source binding -> evidence matrix -> reviewed design classification -> cross-study synthesis -> grounded article -> audit -> figure briefs -> human review/export`

No stage is allowed to silently substitute search snippets, model memory, or vendor claims for primary evidence.

## Canonical acceptance benchmark

The first benchmark is the orchid foliar-feeding question. The regression fixture verifies that source-bound evidence for leaf uptake and root-versus-leaf uptake can be explicitly classified after review, converted into direct claims, rendered into a newsletter-style article with sentence-level claim IDs, audited to publication-ready status, and accompanied by evidence-bound figure briefs while remaining unpublished pending human review.
