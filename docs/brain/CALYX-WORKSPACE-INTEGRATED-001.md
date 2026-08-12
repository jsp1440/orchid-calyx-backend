# CALYX-WORKSPACE-INTEGRATED-001

## Purpose

Consolidate the useful deltas from stale/stacked PRs #873, #885, and #887 onto current `main` so the Calyx conversation surface can return grounded workspace outputs, Matrix can emit a derived identification panel, and Mission Control can report provider readiness without exposing secrets or stale acceptance.

## Implemented

- Speak release advances to `CALYX-SPEAK-005-WORKSPACE-OUTPUTS`.
- Retrieval results become server-grounded table outputs with row-level `result_id` and citation/revision provenance.
- Brain supporting/contradicting Candidate Knowledge is explicitly `generated=true`, `evidence_status=derived` and never represented as direct source evidence.
- Missing evidence becomes an explicit derived uncertainty panel rather than being filled from model memory.
- Empty/casual tool state produces no fabricated outputs.
- Matrix identification evaluation returns one bounded derived ranking panel, capped at 20 candidates, while preserving full 200-character accepted taxon IDs.
- Matrix output explicitly does not assert a verified identification.
- Speak status exposes secret-safe reply-provider readiness.
- Live provider acceptance is valid only when the attested model and attested Speak release match the current runtime configuration and release.
- Endpoint URLs and API keys are never returned by provider-readiness status.

## Governance

- Workspace objects are built server-side from actual tool/module results, not authored by the language model.
- Workspace outputs are not automatically evidence.
- Conversation cannot promote Candidate Knowledge, publish scientific knowledge, activate taxonomy, deploy, or mutate the Knowledge Graph.
- Matrix rankings remain decision support only.
- Provider readiness does not configure or call a provider and spends no credits.

## Validation gate

The consolidated exact head must pass:

1. compile of Speak, workspace, Matrix and provider-readiness modules;
2. focused workspace, Matrix and provider-readiness regressions;
3. adjacent Speak/context/conversation tests;
4. Ruff;
5. diff hygiene;
6. BUILD-088E and workflow-governance regression lanes where available.

GitHub-hosted runner allocation was returning `steps: null` for the predecessor branches at reconstruction time. Such zero-step runs are infrastructure failures and are not counted as code validation. Do not merge this replacement until trusted execution succeeds on its unchanged head.

## Supersession

After this current-main replacement is validated and merged, PRs #873, #885 and #887 should be closed as superseded. Their review history remains useful provenance, but their stale/stacked ancestry should not be merged directly.
