# BUILD-618-R4 — Normalized causal applicability scope on canonical main

## Status

IMPLEMENTED / EXACT-HEAD VALIDATION REQUIRED.

This reconstruction starts directly from canonical `main` after the canonical mechanistic Candidate Knowledge and publication-readiness layers were integrated. Historical BUILD-618-R2 PR #787 and superseded BUILD-618-R3 PR #800 are source material only and are not integration authority.

## Canonical parent chain

- BUILD-615 canonical Candidate Knowledge merge: `efdd0b02295d4fccf0628ec116552ac41dc76d5c`.
- BUILD-616R read-only publication planner merge: `46112f1bdfe0ccf724616b9c7925a8652e48c9e2`.
- BUILD-617R3 read-only contradiction accounting merge: `c89826e808f09555c4662ec03e61d89bdf1f4ebb`.
- BUILD-616R corrective review/provenance hardening merge: `677a506ab61338e9d9a13ece67d972c2c22a044c`.

BUILD-618-R4 adds scope semantics on top of those canonical contracts; it does not replace or weaken them.

## Objective

Make causal applicability explicit and deterministic. Missing applicability remains `unknown`, never silently global. Bounded claims require material applicability evidence. Global claims require explicit justification and cannot carry local bounds.

## Scientific invariants

- Candidate Knowledge duplicate identity remains governed by the canonical Candidate Knowledge service; BUILD-618 does not redefine it.
- `CausalScope` is extra-field-forbidden and deterministic.
- Whitespace-only list entries do not count as applicability evidence.
- Semantically empty mapping bounds such as null, blank, empty list, empty mapping, or blank key/value do not count as applicability evidence.
- Categorical mapping keys and string values are case-folded and whitespace-normalized before applicability identity or scope hashing.
- `bounded` requires at least one real normalized applicability dimension.
- `global` requires explicit justification and rejects local bounds.
- Candidate Knowledge preserves normalized causal scope in qualifiers and graph previews.
- Publication readiness fails closed on unknown or invalid scope and emits no operations while blocked.
- Publication plans retain the canonical BUILD-616R review snapshot, exact Candidate Knowledge provenance, canonical-key endpoint resolution, contradiction blockers, and `publication_adapter_available=false`.
- Contradiction identity uses canonical endpoints plus normalized applicability dimensions. Narrative notes, global justification, and derived scope IDs cannot split a real contradiction.
- For an explicitly unknown scope only, experimental and quantitative context remain conservative disambiguators so unspecified claims are not over-collapsed into a single contradiction group.
- Different real bounded applicability dimensions remain distinct.

## Review remediation from superseded R3

Three demonstrated findings from PR #800 are incorporated here:

1. The inherited BUILD-617 fixture now declares distinct bounded causal scopes when testing distinct tissue applicability; experimental narrative alone is not treated as scientific scope.
2. Semantically empty mapping bounds are rejected rather than satisfying the bounded-scope requirement merely because the outer dictionary is non-empty.
3. Equivalent categorical mapping text is normalized before hashing, preventing capitalization/whitespace differences from evading contradiction grouping.

Dedicated adversarial regressions cover all three cases.

## Governance

This build performs no scientific review decision, contradiction resolution, scientific publication, automatic Candidate Knowledge promotion, canonical Knowledge Graph mutation, production database migration, taxonomy activation, or deployment. It introduces no competing publication executor or provenance representation.

## Validation contract

The dedicated BUILD-618 workflow compiles and lints causal-scope, mechanistic Candidate Knowledge, contradiction, and publication-plan surfaces; runs BUILD-618 adversarial regressions together with BUILD-617/616/615 prerequisites; asserts the permanent scope/publication boundaries; and checks diff hygiene. Applicable Workflow Governance, Canonical Brain, Calyx Brain Integration, Brain E2E, Candidate Knowledge/publication-control, compile, lint, and formatting gates must all be executable-green on the unchanged exact head before merge.

## Child dependency

After BUILD-618-R4 is merged to canonical main, BUILD-619 must be synchronized/reconstructed directly on that merge before any BUILD-620 or BUILD-621 validation can be reused for merge. Historical child validations remain evidence of behavior only, not canonical-base validation.
