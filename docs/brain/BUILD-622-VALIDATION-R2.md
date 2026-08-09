# BUILD-622-R2 Validation Record

Status: executable-green and ready for review, subject to prerequisite merge sequencing.

Integration base: BUILD-621-R2 / PR #790 (`feature/build-621-plant-diagnostic-context-r2`).

Validated code head: `b297cde6ad1b782248433810fa82d1ab8a21f414`.

## Canonical architecture role

BUILD-622 is an interpretation layer over the existing Brain and Knowledge Graph. It does not create a competing reasoning or knowledge store.

The ranker consumes BUILD-621 diagnostic context, whose canonical channel is BUILD-619 scoped Reasoning Map output and whose local channel is BUILD-620 bounded single-plant observation evidence. It returns diagnostic hypotheses only.

Knowledge-state boundaries remain explicit:

- graph/source records are evidence;
- deterministic Reasoning Map paths are explanatory inference over canonical graph evidence;
- BUILD-620 plant observations remain local `CULTIVATION_OBSERVATION` Candidate Knowledge and do not establish mechanisms;
- BUILD-622 ranked items are hypotheses, not Candidate Knowledge, reviewed knowledge, or published knowledge;
- reviewed/published scientific promotion remains governed by the existing Candidate Knowledge, Reasoning Ledger, contradiction/review, and controlled publication paths.

Local observations contribute `0.0` to rank score and causal confidence. Applicable canonical paths retain canonical path confidence. Indeterminate paths receive an explicit scope penalty. Out-of-scope paths are not ranked.

## Executable validation

The first executable BUILD-622-R2 run reached compile successfully and exposed two Ruff import-organization findings in `app/brain/routes.py` and `tests/test_build_622_diagnostic_hypotheses.py`. Both were corrected without changing scientific or governance behavior.

Exact corrected code head `b297cde6ad1b782248433810fa82d1ab8a21f414` then passed all applicable workflows:

- BUILD-622 Diagnostic Hypothesis Validation — run `31323630590`;
- BUILD-621 Plant Diagnostic Context Validation — run `31323630576`;
- BUILD-619 Reasoning Scope Validation — run `31323630566`;
- Canonical Brain Validation — run `31323630545`;
- Calyx Brain Integration Validation — run `31323630558`;
- CALYX Brain End-to-End Certification — run `31323630551`;
- CALYX Workflow Governance Audit — run `31323630581`;
- CALYX Core Rebase 003 — run `31323630535`;
- CALYX Agent 001 — run `31323630542`;
- CALYX Agent 003 — run `31323630552`;
- CALYX Agent 004 — run `31323630546`;
- CALYX Journalism MVP — run `31323630565`;
- CALYX Brain Education Design — run `31323630523`.

The dedicated BUILD-622 job passed dependency setup, compile, Ruff lint, Ruff formatting, hypothesis plus BUILD-619→621 prerequisite regressions, protected route verification, and repository hygiene.

## Governance

BUILD-622 remains read-only interpretation support. It grants no authority to:

- create or approve Candidate Knowledge automatically;
- treat a local observation as causal confirmation;
- resolve contradictions;
- mutate the canonical Knowledge Graph;
- mutate the semantic index as canonical truth;
- publish scientific knowledge;
- activate taxonomy;
- mutate production data; or
- deploy.

Any hypothesis that is to become a scientific assertion must enter the canonical governed evidence/review/publication path with provenance preserved.

## Integration dependency

The BUILD-618→622 R2 lineage is mergeable and executable-green, but its integration root still depends on BUILD-617-R2 → BUILD-616 → BUILD-615. BUILD-615 and BUILD-616 were validated on their own exact heads but their historical branches are currently non-mergeable against `main`; they require canonical current-main reconstruction before the downstream R2 chain can be integrated in order.
