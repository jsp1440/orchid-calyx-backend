# CALYX-SPECIES-KNOWLEDGE-001 — Evidence-grounded species exhibit

## Objective

Complete the backend contract required by the homepage species exhibit so the frontend can render distinct species stories without inventing scientific claims or falling back to genus-level narrative.

## Implemented

- Extends `calyx-species-exhibit-v1` additively.
- Normalizes a presentation binomial while retaining the full source scientific-name string and authorship text.
- Deduplicates cards by canonical taxon ID and normalized binomial.
- Chooses representative media deterministically and avoids reusing a representative URL across cards when another candidate is available.
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

## Current-main release recovery

Original PR #531 was created against an earlier current-main point and later drifted behind the active branch. A merge-base comparison showed that the subsequent mainline commits did not modify `app/species_exhibit`, its contract, or its focused tests. The implementation was therefore rebuilt on `feature/calyx-species-knowledge-001-current-main-r2` from the post-Atlas mainline instead of forcing the stale PR.

The previous backend zero-step runner failures are no longer treated as a standing code blocker. Fresh executable validation on the exact replacement head is required before merge.

## Evidence policy

The deterministic caption is not a language-model inference. It is a presentation of one persisted relation in the form:

`<species>: <edge type> — <persisted display label>.`

If the persisted graph does not support a relation, no caption is produced.

## Validation surface

Focused contract tests cover unavailable-state semantics, binomial/authorship separation, cross-card media URL deduplication, evidence-bound caption/fact rendering, conservative degraded behavior, Decimal-backed confidence values, deterministic content-free evidence receipts, unavailable-domain preservation, and fully available cards with media plus graph evidence.

A dedicated workflow validates compile, Ruff, focused pytest, and diff hygiene on current main.

## Governance

No taxonomy activation, scientific publication, Knowledge Graph mutation, production deployment, credential exposure, browser-side scientific scoring, or automatic identity verification is introduced. Human/scientific review boundaries remain intact.
