# BUILD-086A — Candidate Knowledge Extraction Foundation

BUILD-086A adds an isolated, review-first candidate knowledge layer over canonical BUILD-084 evidence. It does not publish taxonomy records or Knowledge Graph nodes or edges.

The additive `oc_candidate_knowledge` schema retains versioned extraction runs, resumable run items, candidates, exact source-anchor evidence links, duplicate and conflict groups, review items, and audit events. Every candidate remains unpublished even after operator approval; later controlled publication work must make a separate decision.

Candidate types cover taxa, traits, morphology/glossary terms, ecological relationships, geographic occurrences, phenology, conservation assertions, measurements, molecular markers, and cultivation observations. Deterministic structured inputs are preferred, with conservative bounded text rules as a fallback. Candidate confidence remains decomposed from source and anchor confidence and is never represented as truth.

Preview creates no candidates. Execution is idempotent by canonical evidence, extractor, ruleset, and exact anchors. Changed assertions create retained versions; equivalent assertions aggregate evidence and enter duplicate review; incompatible values enter conflict review. Cancellation preserves completed item boundaries and resume processes only unfinished work.

Copyright display policy controls stored quotations independently of extraction: metadata-only and unknown-rights sources retain provenance without source text, limited-preview sources are bounded, and internal text requires stored internal-use permission. All APIs require repository-standard owner/API-key authentication.
