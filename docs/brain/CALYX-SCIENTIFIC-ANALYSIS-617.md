# CALYX-617 — Scientific Computing & Analysis Engine

## Status
Sixth bounded implementation slice completed on top of `feature/calyx-research-station-453` and retained in draft PR #618.

Canonical architecture is preserved in the Orchid Continuum Brain as `14_ENGINEERING/SCICOMP-001-scientific-computing-analysis-engine-blueprint.md`, with implementation contracts SCICOMP-001B through SCICOMP-001F.

## Purpose
Give the private Research Station a reproducible statistical and mathematical execution layer without turning Calyx into an opaque calculator or giving computed results, diagnostics, comparisons, filters, or visualizations publication authority.

## Operational surface

- `runtime/scientific_analysis.py` — deterministic statistical kernel and capability registry.
- `runtime/research_analysis_workflow.py` — immutable Analysis Plans, exact Research Station dataset binding, transform/filter execution, receipts, and replay-safe notebook linkage.
- `runtime/scientific_transforms.py` — typed variable metadata and deterministic derived-variable transformations.
- `runtime/scientific_filters.py` — bounded declarative row filtering with excluded-row identity and reason receipts.
- `runtime/scientific_diagnostics.py` — immutable, plot-ready descriptive diagnostics bound to exact analysis identity.
- `runtime/scientific_comparison.py` — immutable descriptive comparison of analysis runs without model ranking.
- `runtime/scientific_result_artifacts.py` — normalized result tables and diagnostic-backed figure specifications for frontend rendering.
- `app/routers/scientific_analysis.py` — protected Mission Control APIs.
- dedicated deterministic regression suite and CI with permanent non-authority assertions.

### Supported statistical methods

- `describe.v1` — descriptive statistics.
- `pearson.v1` — Pearson product-moment correlation.
- `ols.v1` — simple ordinary least-squares regression.

The current slice intentionally omits p-values and significance claims.

## Analysis Plan contract
A pre-execution immutable plan contains:

- explicit research question and rationale;
- registered Research Station dataset ID and raw checksum;
- typed variables with role and unit metadata;
- explicit method/version and parameters;
- missing-data policy;
- versioned deterministic transformations;
- versioned declarative row filters;
- method assumptions;
- authenticated creator identity and creation time;
- permanent non-publication/non-KG-mutation governance flags.

Numeric source variables require explicit units. Methods and filters may use only declared variables, including declared derived variables produced by the governed transformation engine.

## Governed transformation engine
`calyx-scientific-transforms/v1` supports deterministic creation of new derived variables without overwriting source measurements: `log10`, `sqrt`, `center`, `zscore`, and `scale` with an explicit finite nonzero factor.

Each transform declares source variable, target variable, target unit, and optional role. Transform execution emits a receipt containing complete/missing counts, execution context such as mean/sample SD/factor when applicable, and an output SHA-256. Domain errors, zero variance, missing source variables, nonnumeric inputs, duplicate targets, invalid units/roles, and unsupported operations fail closed.

## Governed row filter engine
`calyx-scientific-filters/v1` replaces free-text exclusions with explicit inclusion predicates. A row is retained only when every declared predicate evaluates true.

Supported operators: `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in`, `not_in`, `is_missing`, `not_missing`.

Every filter must name a declared variable, use a supported typed operator, and include a non-empty `reason_code`. Numeric comparison operators require numeric variables and finite numeric thresholds. Filters may reference derived variables because transformations execute before filters.

Free-form Python/SQL/JavaScript expressions, arbitrary predicates, regex code, procedural callbacks, and implicit outlier removal are not permitted. Legacy free-text `exclusions` are rejected and callers must use governed `row_filters`.

Filter execution produces a deterministic receipt containing engine version, predicate mode, rows before/after, excluded count, stable per-run excluded-row identities, source positions, reason codes, normalized filter definitions, and receipt SHA-256. A filter that removes every row fails closed with `ANALYSIS_ROW_FILTER_REMOVED_ALL_ROWS`.

## Three-stage checksum binding
Execution first verifies submitted raw rows against the registered Research Station dataset SHA-256. Only after that check passes may declared transforms and filters execute.

Every plan-bound run distinguishes:

1. `raw_dataset_checksum_sha256` — registered source dataset identity;
2. `pre_filter_analytical_rows_sha256` — transformed rows before row filtering;
3. `analytical_rows_sha256` — exact post-filter rows passed to the statistical kernel.

This prevents dataset substitution, silent transformation drift, and silent analytical-population drift.

## Downstream artifacts
`calyx-scientific-diagnostics/v1` creates immutable descriptive diagnostic payloads bound to exact plan/analysis/input/result identity. `calyx-scientific-comparison/v1` compares runs without selecting a winner. `calyx-scientific-result-artifact/v1` provides normalized result tables and diagnostic-backed figure specifications. Diagnostics, comparisons, tables, and figure specifications remain distinct from scientific interpretation.

## Research Station notebook integration
Successful plan execution writes a machine-readable, non-interpretive receipt into the project notebook. The receipt includes raw/pre-filter/post-filter checksums, transformation receipts, filter receipt, analysis/result identity, warnings, and governance state. Replay is idempotent and conflicting content fails closed rather than rewriting history.

## Front-end contract
Before execution the Workbench should show raw dataset identity, source/derived variables and units, transformations, each row filter with its reason code, method/rationale, assumptions, and blockers. After validation/execution it should display before/after filter counts, excluded-row identities/reasons, raw/pre-filter/post-filter checksums, analysis/result/diagnostic/artifact identities, transformation/filter receipts, warnings, notebook receipt, and optional run comparison.

The frontend must not offer an unlabeled “remove outliers” action. Any future convenience control must compile into the same visible governed filter contract before execution.

## Governance
Permanent current-slice boundaries:

- no arbitrary Python/R/shell/SQL/JavaScript execution;
- no autonomous model selection;
- no autonomous scientific publication;
- no Knowledge Graph mutation;
- no fabricated significance;
- no silent conversion of missing values to zero or absence;
- no source-column mutation by transforms;
- no undeclared/unversioned transformations;
- no free-form filter expressions;
- no implicit outlier removal;
- no anonymous excluded rows;
- every filter requires a reason code;
- diagnostics are descriptive, not inferential verdicts;
- comparisons do not select a winner;
- figure specs are rendering instructions, not interpretations;
- no silent conversion of computed output into scientific interpretation;
- human review remains required before scientific conclusions become reviewed claims.

## Validation
The filter slice added regression coverage for unchanged plans, explicit thresholds, derived-variable filters, before/after hashes and counts, excluded-row identity/reasons, zero-row fail-closed behavior, legacy free-text exclusion rejection, replay-safe notebook receipts, existing transform/diagnostic/comparison/result-artifact behavior, and Research Station regressions. The first exact-head run passed all 29 behavioral tests and all governance assertions; Ruff found only import formatting, which was corrected without weakening the gate. Final exact-head CI is required before this slice is considered validated.

## Next implementation priorities

1. implement the Research Station Analysis Workbench frontend against these live contracts rather than mocks;
2. expand diagnostics where justified, including influence/residual distribution measures;
3. define the inferential-method governance contract for effect sizes, confidence intervals, assumptions, multiplicity, and power before adding hypothesis-testing methods;
4. add export/render artifacts and publication-quality rendering profiles;
5. only later design a separately sandboxed Python/R execution environment.

## Relationship impact

```text
Research Project
  -> Registered Raw Dataset + checksum
  -> Typed Variables + Units
  -> Immutable Analysis Plan
  -> Raw Dataset Verification
  -> Versioned Derived-Variable Transformations
  -> Pre-filter Analytical Dataset + checksum
  -> Governed Row Filters + exclusion receipt
  -> Final Analytical Dataset + checksum
  -> Analysis Run
  -> Diagnostic Artifact
  -> Result Table + Figure Specifications
  -> Optional Run Comparison
  -> Research Station Notebook / Workbench
  -> Candidate Interpretation
  -> Human Review
```

No new scientific fact is created merely because an analysis, exclusion receipt, diagnostic, comparison, table, or figure specification exists.
