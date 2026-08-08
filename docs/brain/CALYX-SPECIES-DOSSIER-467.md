# CALYX-467 — Canonical species dossier and federation gateway

Status: IMPLEMENTED / VALIDATED / GOVERNED REVIEW-ONLY

## Delivered

- Stable-taxon keyed canonical dossier envelope with identity and all required domain slots: nomenclature, media, distribution, Atlas, ecology, pollination, mycorrhiza, conservation, literature, cultivation, and graph paths.
- Explicit `available`, `partial`, `review_required`, and `unavailable` domain states; missing upstream data degrades gracefully instead of becoming invented zeroes or empty scientific conclusions.
- Provenance is required for every available/partial/review domain and for the dossier envelope itself.
- Contradiction state is preserved per domain and summarized at the envelope level.
- Adaptive resolver supports stable taxon ID, exact scientific name, and exact alias resolution while returning explicit ambiguity or unmatched states.
- Partner federation links carry independent permission dimensions for link-out, ingestion, redistribution, and derivative use. Any `allowed` permission requires supplied evidence; unspecified dimensions default to `unknown` and are never inferred.
- Owner-scoped persistence, deterministic dossier digests, replay stability, protected Mission Control create/read/resolve/readiness APIs, and focused fixture tests.

## Integration model

CALYX-467 is intentionally an assembly boundary rather than another competing domain database. Governed taxonomy, media, occurrence/distribution, Atlas, ecological interaction, mycorrhizal, conservation, literature, cultivation, and Knowledge Graph packets can be supplied as domain items plus provenance. A domain that has not yet been supplied remains explicitly `unavailable`.

This permits the dossier to operate before every upstream vertical is simultaneously deployed while retaining exact missing-domain visibility. It also avoids silently importing branch-local representations from still-unmerged dependency work.

## Governance boundaries

This slice does not claim partner permissions without evidence, perform provider ingestion, mutate the production Knowledge Graph, publish scientific conclusions, deploy production changes, or authorize merge. Federation permission state is informational/review-only and unknown by default.

## Validation

Implementation commit `264bd3f7888df1274bfd1e524156d8318964a487` completed the dedicated validation gate:

- CALYX Species Dossier 467: success; compile, 9 deterministic dossier/API tests, permanent federation/non-authority assertions, Ruff, and diff hygiene all passed.
- CALYX Workflow Governance Audit: success.
- CALYX-AUTONOMY-DEPLOYMENT-001: success.
- CALYX-SUPERVISED-PILOT-001: success.

The generic BUILD-088E workflow was still running when this Brain entry was updated; no failure was observed. PR #635 remains draft/unmerged. This documentation-only validation-record commit remains subject to the same PR checks.
