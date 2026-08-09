# BUILD-621-R2 Validation Record

Status: executable-green and ready for review.

Integration base: BUILD-620-R2 / PR #789 (`feature/build-620-local-observation-bridge-r2`).

Validated code head: `c10c19d79d4f480b3291fa90a017241d4767b5b5`.

Scope: read-only plant diagnostic context composition. The build combines BUILD-619 scoped canonical reasoning with BUILD-620 bounded local plant observations while keeping those channels explicitly separate. Local observations do not become causal claims or canonical mechanisms.

## Executable validation

Dedicated BUILD-621 workflow run `31323237718` completed successfully. It passed dependency setup, compile, Ruff lint, Ruff formatting, BUILD-621 diagnostic-context regressions, BUILD-620 local-observation regressions, BUILD-619 scoped-reasoning regressions, protected diagnostic-route verification, and repository hygiene.

Applicable broad checks on the same exact code head also completed successfully:

- BUILD-619 Reasoning Scope Validation — run `31323237747`;
- CALYX Workflow Governance Audit — run `31323237749`;
- Canonical Brain Validation — run `31323237734`;
- Calyx Brain Integration Validation — run `31323237720`;
- CALYX Brain End-to-End Certification — run `31323237713`;
- CALYX Agent 001 — run `31323237717`;
- CALYX Agent 003 — run `31323237743`;
- CALYX Agent 004 — run `31323237741`;
- CALYX Core Rebase — run `31323237757`;
- CALYX Journalism MVP — run `31323237709`;
- CALYX Brain Education Design — run `31323237742`.

## Findings corrected before readiness

The first executable BUILD-621 pass (`31323192550`) reached compile and lint successfully but exposed Ruff formatter drift in one long assertion in `tests/test_build_621_plant_diagnostic_context.py`. The assertion was reformatted and the complete validation/broad suite was rerun on the exact corrected code head. No scientific, behavioral, or governance gate was weakened.

## Governance

No Candidate Knowledge mutation, scientific review decision, contradiction resolution, publication, canonical Knowledge Graph mutation, production database mutation, taxonomy activation, or deployment is authorized. Diagnostic context remains a read-only evidence-composition surface.
