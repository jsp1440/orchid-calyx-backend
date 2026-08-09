# BUILD-622-R2 — Diagnostic Hypothesis Ranking

## Status

Reconstructed directly on executable-green BUILD-621-R2 / PR #790. Historical PR #774 is closed and is source material only.

Executable-green code head: `b297cde6ad1b782248433810fa82d1ab8a21f414`.

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

## Validation

The first executable R2 run reached project code and exposed two Ruff import-organization findings in `app/brain/routes.py` and `tests/test_build_622_diagnostic_hypotheses.py`. Both were corrected without behavioral or governance changes.

Exact code head `b297cde6ad1b782248433810fa82d1ab8a21f414` is fully green across all 13 applicable workflows:

- BUILD-622 Diagnostic Hypothesis Validation run `31323630590` — success;
- BUILD-621 Plant Diagnostic Context Validation `31323630576` — success;
- BUILD-619 Reasoning Scope Validation `31323630566` — success;
- CALYX Workflow Governance Audit `31323630581` — success;
- Canonical Brain Validation `31323630545` — success;
- CALYX Brain End-to-End Certification `31323630551` — success;
- Calyx Brain Integration Validation `31323630558` — success;
- CALYX-CORE-REBASE-003 `31323630535` — success;
- CALYX-AGENT-001 `31323630542` — success;
- CALYX-AGENT-003 `31323630552` — success;
- CALYX-AGENT-004 `31323630546` — success;
- CALYX-BRAIN-EDU-DESIGN-001 `31323630523` — success;
- CALYX-JOURNALISM-MVP `31323630565` — success.

The dedicated BUILD-622 workflow passed compile, Ruff lint/format, BUILD-622/621/620/619 regressions, protected-route verification, and repository hygiene.

No unresolved review threads exist on PR #792. Merge sequencing still requires BUILD-621-R2 #790 and its validated prerequisite chain first.
