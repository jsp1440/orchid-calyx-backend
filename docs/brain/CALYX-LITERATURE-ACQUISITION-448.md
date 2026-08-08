# CALYX Literature production acquisition and evidence binding — issue #448

Date: 2026-08-07
Dependencies: merged artifact registry/review infrastructure (#440–#441)
Status: bounded implementation delivered for deterministic network-independent validation; no production acquisition or publication performed.

## Goal

Provide the next production-shaped Literature Intelligence slice without creating a second scientific authority or relying on live OCR/network services.

Lifecycle:

`caller-supplied DOI/URL/upload bytes → immutable source/revision/run identity → text/PDF detection → exact extraction spans → optional reviewed-taxonomy reconciliation → explicit Candidate Knowledge handoff → readiness`

## Acquisition and document detection

`runtime/literature_acquisition.py` accepts bounded source bytes and an optional source reference.

Source identity supports:

- DOI references, including `doi.org` URLs;
- ordinary HTTP(S) source URLs;
- uploaded files when no external source reference is supplied.

Document detection supports:

- UTF-8 uploaded text;
- native PDFs when extracted page text is materially present;
- scanned/image PDFs when PDF parsing succeeds but meaningful embedded text is absent.

Scanned PDFs become `OCR_REQUIRED`. This slice intentionally does not invoke live OCR.

## Immutable identities and provenance

The service derives deterministic identities for:

- source (`source_id`) from the canonical DOI/URL/upload key;
- revision (`revision_id`) from source SHA-256;
- extraction run (`run_id`) from source, revision, extractor version, and extraction SHA-256.

Source bytes are preserved immutably under the run workspace. Extracted text, evidence spans, manifest, taxonomy review, candidate handoffs, and checkpoint state are durable local artifacts.

Replay of the same immutable inputs resolves to the same run identity.

## Exact evidence binding

Evidence spans are exact character ranges over the stored `extracted.txt` artifact. Each span records:

- stable span ordinal;
- `char_start` / `char_end`;
- exact span text;
- span SHA-256.

Candidate handoffs must reference a valid nonempty extraction span. Invalid/out-of-range evidence is rejected rather than repaired heuristically.

## Taxonomy reconciliation

An operator may configure reviewed taxonomy staging using:

`CALYX_TAXONOMY_REVIEW_STAGING_PATH`

Reconciliation is conservative:

1. exact supplied `taxon_key` match;
2. exact normalized scientific-name match;
3. ambiguous or unmatched identity remains explicit and requires review.

No fuzzy taxonomic inference or taxonomy activation occurs.

## Candidate Knowledge handoff

The implementation reuses the existing canonical `app.parallel_platform.brain_candidate_handoff` adapter and therefore the existing Candidate Knowledge boundary rather than creating a competing candidate store.

Explicit proposed claims retain:

- domain, subject, predicate, and object;
- confidence;
- exact evidence span;
- literature source/revision/run provenance and hashes;
- support versus counterevidence/contradiction state.

Handoff IDs are deterministic. Replay does not create a second handoff record in the literature workspace. Candidate outputs remain review-required, unpublished, and non-graph-mutating.

## Protected Mission Control API

Owner/API-key protected routes under:

`/brain/mission-control/literature`

- `POST /intake` — bounded multipart source intake with optional DOI/URL reference;
- `POST /{run_id}/reconcile-taxa` — reviewed taxonomy reconciliation;
- `POST /{run_id}/candidate-handoffs` — explicit evidence-bound Candidate Knowledge handoff;
- `GET /{run_id}/evidence` — bounded exact evidence-span retrieval;
- `GET /{run_id}/readiness` — deterministic readiness state.

## Resumability and checkpoints

Each run persists checkpoint state for extraction completion, OCR requirement, candidate-handoff count, and completion state. Re-entry occurs from immutable artifacts instead of recomputing identities or discarding prior evidence.

## Permanent non-authority

The readiness contract always reports:

- `ready_for_publication=false`;
- `scientific_publication_authorized=false`;
- `knowledge_graph_mutation_authorized=false`;
- `live_ocr_authorized=false`.

No production Knowledge Graph writer, publication call, credential store, or OCR network dependency exists in this slice.

## Validation

Dedicated workflow:

`.github/workflows/calyx-literature-acquisition-448.yml`

Validation covers:

- Python compilation;
- DOI/URL/upload identity contracts and replay;
- exact evidence spans;
- native/scanned PDF detection contracts;
- taxonomy reconciliation and unresolved review;
- Candidate Knowledge support/counterevidence provenance handoff;
- invalid span rejection;
- protected Mission Control API;
- upload/source-ref bounds;
- existing Candidate Knowledge regressions;
- artifact-registry regressions;
- permanent non-authority assertions;
- Ruff and `git diff --check`.

Corrective validation history:

- initial dedicated CI identified a stale/nonexistent Candidate Knowledge test path in the new workflow; the workflow was corrected to reference current canonical tests;
- the next run exposed that a local Candidate Knowledge integration fixture needed explicit in-memory components because the global production dependency correctly fails closed without a configured database; the test now injects the canonical `MemoryCandidateRepository` + `CandidateExtractionService` boundary rather than bypassing it;
- an unrelated async regression file was removed from this network-independent lane because its own pytest plugin dependency is not part of this build's runtime contract;
- the next run passed 22 deterministic functional/regression tests and permanent non-authority assertions, then Ruff exposed two local style defects; both were corrected in source rather than waived.

A fresh exact-head CI cycle is required after this Brain update before the implementation is reported as final DELIVERED evidence on issue #448.

## Explicit non-actions

No live DOI/URL fetching, OCR service invocation, production literature crawl, scientific publication, production Knowledge Graph mutation, deployment, merge, credential storage, or fabricated production counts are performed.
