# BUILD-622 — Diagnostic Hypothesis Ranking

## Status

Implemented on `feature/build-622-diagnostic-hypothesis-ranking`, stacked on BUILD-621. This build must not merge before the BUILD-615→621 prerequisite stack is validation-cleared and GitHub Actions hosted-runner issue #481 is resolved.

## Purpose

BUILD-622 converts the read-only plant diagnostic context into a ranked set of **possible explanations** without turning those explanations into scientific claims.

The flow is:

`canonical scoped reasoning + bounded local plant history → diagnostic hypotheses`

It is deliberately not:

`local observation → proven causal mechanism`

## Protected API

`POST /brain/diagnostic-hypotheses`

The request carries a BUILD-621 diagnostic context request plus ranking controls.

## Ranking policy

Each hypothesis originates from an existing canonical reasoning-map path.

- scope-qualified applicable paths retain their canonical path confidence as the ranking score;
- indeterminate-scope paths may remain visible but receive a 0.5 applicability penalty;
- out-of-scope paths are excluded from ranking and returned separately for transparency;
- local observations are attached as plant-specific diagnostic context but contribute **0.0** to the causal ranking score;
- local observations never increase canonical path confidence;
- local observations never constitute causal confirmation.

This conservative policy prevents the system from treating correlation or resemblance in one cultivated plant as evidence that a published mechanism caused that response.

## Hypothesis semantics

Every returned hypothesis is labeled:

- `status = diagnostic_hypothesis_only`;
- `scientific_claim = false`;
- `causality_proven = false`;
- `local_observations_confirm_mechanism = false`;
- `requires_additional_discriminating_evidence = true`.

Stable hypothesis IDs are deterministic hashes of the plant identity, path nodes/edges, applicability state, and canonical path confidence.

## Evidence separation

BUILD-621 remains authoritative for the two evidence channels:

1. canonical scoped Knowledge Graph mechanisms;
2. local Candidate Knowledge cultivation observations.

BUILD-622 consumes those channels but does not merge them into a shared evidence class and does not write either store.

## Governance

The ranker is read-only and explicitly lacks:

- Candidate Knowledge creation authority;
- publication authority;
- canonical graph mutation authority;
- contradiction-resolution authority;
- scientific-review authority.

A ranked diagnostic hypothesis can inform a grower, researcher, or later experimental-design workflow. It cannot become a canonical scientific assertion without a separate evidence-preserving candidate/review/publication process.

## Validation

`tests/test_build_622_diagnostic_hypotheses.py` verifies:

- applicable canonical paths become ranked hypotheses;
- deterministic descending ranking;
- local observations do not change rank scores;
- local observations do not confirm causality;
- out-of-scope paths are excluded;
- indeterminate paths are penalized;
- callers can suppress indeterminate hypotheses;
- no Candidate Knowledge mutation, graph mutation, or publication authority is introduced.

The dedicated BUILD-622 workflow also executes BUILD-619, BUILD-620, and BUILD-621 regression suites plus route import, compile, Ruff, formatting, and repository hygiene checks.

## Infrastructure blocker

At implementation time, GitHub-hosted Actions jobs continue to fail before step 1 with `steps=null`. A fresh rerun of BUILD-621 reproduced the same runner-allocation failure. BUILD-622 therefore remains draft/non-mergeable by policy until executable CI returns.

## Next dependency

After executable CI is restored, the next useful layer is a **discriminating-evidence planner**: for each ranked hypothesis, identify observations or measurements that would most efficiently distinguish competing explanations. That planner must remain advisory and must not fabricate evidence or automatically change hypothesis status.
