# BUILD-622-R2 — Diagnostic Hypothesis Ranking

## Status

Reconstructed directly on executable-green BUILD-621-R2 / PR #790. Historical PR #774 is closed and is source material only.

## Purpose

BUILD-622 converts the read-only plant diagnostic context into ranked **possible explanations** without turning those explanations into scientific claims.

Flow:

`canonical scoped reasoning + bounded local plant history -> diagnostic hypotheses`

It is explicitly not:

`local observation -> proven causal mechanism`

## Protected API

`POST /brain/diagnostic-hypotheses`

The request embeds the BUILD-621 diagnostic-context request and bounded ranking controls.

## Ranking policy

- applicable canonical paths retain canonical path confidence as rank score;
- indeterminate-scope paths may remain visible with a 0.5 applicability penalty;
- out-of-scope paths are excluded from ranking and returned separately;
- local observations contribute 0.0 to rank score and causal confidence;
- local observations never constitute causal confirmation.

Every returned item is labeled `diagnostic_hypothesis_only`, not a scientific claim, and requires additional discriminating evidence.

## Evidence and authority boundaries

BUILD-621 remains authoritative for separation between:

1. canonical scoped Knowledge Graph reasoning;
2. bounded local Candidate Knowledge cultivation observations.

BUILD-622 reads those channels and writes neither store. It has no Candidate Knowledge creation, scientific review, contradiction resolution, publication, canonical graph mutation, production DB mutation, taxonomy activation, deployment, or merge authority.

## Validation contract

Dedicated CI runs:

- compile and Ruff lint/format on the BUILD-622 surface;
- `tests/test_build_622_diagnostic_hypotheses.py`;
- BUILD-621 diagnostic-context regressions;
- BUILD-620 local-observation regressions;
- BUILD-619 scope-evaluation regressions;
- protected-route import verification;
- repository hygiene.

Readiness requires executable exact-head success plus no unresolved review findings. Merge sequencing requires BUILD-621-R2 #790 and its validated prerequisite chain first.
