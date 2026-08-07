# CALYX-SPECIES-KNOWLEDGE-001 — Evidence-grounded species exhibit

## Objective

Complete the missing backend contract required by the homepage species exhibit so the frontend can render nine distinct species stories without inventing scientific claims or reusing genus narrative.

## Implemented

- Extended `calyx-species-exhibit-v1` additively on current `main`.
- Normalizes a presentation binomial while retaining the complete source scientific-name string and authorship text.
- Deduplicates cards by canonical taxon ID and normalized binomial.
- Chooses representative media deterministically and avoids reusing a media URL across cards when another candidate is available.
- Marks representative media as source-record evidence rather than independently verified identity.
- Projects a caption and distinguishing fact only from an already persisted Knowledge Graph edge.
- Returns `null` caption/fact plus an explicit caveat when no species-specific relation supports prose.
- Derives confidence only from explicit persisted edge confidence scores; missing scores remain unavailable.
- Surfaces contradiction-class graph evidence rather than resolving it silently.
- Emits provenance anchors for taxonomy, representative media, and graph evidence.
- Emits a deterministic SHA-256 evidence receipt over evidence identifiers without embedding evidence contents.
- Preserves unavailable domain states for adapters not yet connected.
- Preserves the legacy `media`, `graph_paths`, `evidence_states`, and `calyx_handoff` fields for compatibility.
- Keeps publication authority and graph mutation disabled.

## Important integration correction

The frontend issue requires server-owned species captions and distinguishing facts. The previous backend implementation returned a Calyx narrative handoff but did not return the public `caption`, `distinguishing_fact`, confidence, provenance, contradiction, or representative-media fields described by the contract. That made a rigorous frontend implementation impossible without browser-side scientific invention. This slice closes that contract gap first.

## Evidence policy

The deterministic caption is not a language-model inference. It is a presentation of one persisted relation in the form:

`<species>: <edge type> — <persisted display label>.`

If the persisted graph does not support a relation, no caption is produced. This is deliberately conservative.

## Validation surface

Focused contract tests cover:
- unavailable-state semantics;
- binomial/authorship separation;
- cross-card media URL deduplication;
- evidence-bound caption/fact rendering;
- no-caption degraded behavior;
- Decimal-backed persisted confidence values;
- deterministic content-free evidence receipts;
- unavailable-domain preservation;
- fully available cards with media and graph evidence.

A dedicated GitHub Actions workflow validates compilation, Ruff, focused pytest, and diff hygiene.

### Validation evidence — 2026-08-07

Backend PR #531 workflow run `31203912347` was invoked for the implementation head, but GitHub terminated the `validate` job before instantiating any steps (`steps: null`). A failed-job retry was not accepted as scientific/code validation because no compile, Ruff, or pytest command executed. This matches the contemporaneous zero-step Actions failure affecting unrelated backend workflows and remains an infrastructure validation blocker, not evidence of a code defect or a successful test run.

The paired frontend implementation in `jsp1440/orchid-continuum-frontend` PR #86 received executable validation:
- Frontend CI run `31204240608`: build and repository lint passed on implementation head `9901fdbf37c2edc6ff0bd3de45974271f6d4dd02`.
- CALYX-SPECIES-EXHIBIT-001 run `31204361071`: dependency install, focused Vitest contract tests, production build, changed-surface ESLint, and diff hygiene all passed on head `49e6e3f8042bb48e459e4c8588d81c1fc36d7431`.
- Frontend CI run `31204361003`: repository production build and repository lint also passed on that final frontend head.

Therefore the browser-side consumer is executable and validated, while backend PR #531 remains draft pending a real backend Actions execution. Zero-step backend failures must not be treated as either pass or application failure.

## Governance

No taxonomy activation, publication, graph mutation, production deployment, credential exposure, browser-side scientific scoring, or automatic identity verification is introduced. Human/scientific review boundaries remain intact.