# CALYX-SYN-004 — Evidence Matrix Extraction

## Mission

Convert verified, exact-source-bound literature evidence into deterministic study/evidence matrix rows without allowing normalized prose to overwrite original provenance or allowing the extractor to overstate study design.

## Contract

Input requires:

- a `PaperKnowledge` literature extraction result
- a canonical literature source binding with CALYX-SYN-002 exact integrity proofs
- a bibliographic record verified by an authoritative provider or publisher

Each output `EvidenceMatrixRow` carries:

- verified bibliographic source identity
- exact evidence anchors
- immutable source hash
- exact excerpt hash
- source character offsets and section
- conservative evidence class
- taxon when uniquely source-resolved
- outcome/predicate
- normalized result text as a derived scientific field
- sample size only when explicitly extracted in a linked measurement
- uncertainty/review state
- validation notes/limitations
- original evidence IDs

## Conservative design classification

Automatically built rows are classified `OBSERVATIONAL`. The builder deliberately does not infer `CONTROLLED_EXPERIMENT` or `DIRECT_TRACER` from persuasive wording. Those stronger classes require a later reviewed design-classification step based on methods and results evidence.

This prevents a result sentence mentioning a tracer, control, isotope, treatment, or comparison from being silently promoted to a stronger evidentiary design than the extracted record proves.

## Hard gates

Matrix construction fails when:

- bibliography is unverified
- verification provider/identifier is missing
- exact source integrity proof is missing
- source claim is missing
- evidence, canonical anchor, or integrity proof is missing
- proof anchor identity does not match the canonical binding

## Governance

- Matrix extraction creates synthesis input, not published Knowledge Graph truth.
- Exact source anchors remain authoritative over normalized text.
- No automatic evidence-class promotion occurs.
- Review and publication controls remain downstream and authoritative.
