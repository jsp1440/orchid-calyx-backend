# CALYX-617 — Scientific Computing & Analysis Engine

## Status
Eighth bounded implementation slice is present on `feature/calyx-scientific-analysis-617` and retained in draft PR #618.

Canonical architecture is preserved in the Orchid Continuum Brain through SCICOMP-001M. The current slice adds a reference-validated uncertainty primitive without registering a new live Analysis Plan method or changing production runtime requirements.

## Purpose
Give the private Research Station a reproducible statistical and mathematical execution layer without turning Calyx into an opaque calculator or giving computed results, diagnostics, comparisons, filters, snapshots, uncertainty artifacts, or visualizations publication authority.

## Operational surface

- `runtime/scientific_analysis.py` — deterministic statistical kernel and capability registry.
- `runtime/scientific_uncertainty.py` — bounded dependency-backed uncertainty primitives; not yet live in the Analysis Plan registry.
- `runtime/research_analysis_workflow.py` — immutable Analysis Plans, exact Research Station dataset binding, transform/filter execution, receipts, and replay-safe notebook linkage.
- `runtime/scientific_transforms.py` — typed variable metadata and deterministic derived-variable transformations.
- `runtime/scientific_filters.py` — bounded declarative row filtering with excluded-row identity and reason receipts.
- `runtime/scientific_dataset_snapshots.py` — private immutable row snapshots cryptographically bound to an already-registered Research Station dataset.
- `runtime/scientific_diagnostics.py` — immutable, plot-ready descriptive diagnostics bound to exact analysis identity.
- `runtime/scientific_comparison.py` — immutable descriptive comparison of analysis runs without model ranking.
- `runtime/scientific_result_artifacts.py` — normalized result tables and diagnostic-backed figure specifications for frontend rendering.
- `app/routers/scientific_analysis.py` — protected Mission Control APIs.
- dedicated deterministic regression suite and CI with permanent non-authority assertions.

### Supported live statistical methods

- `describe.v1` — descriptive statistics.
- `pearson.v1` — Pearson product-moment correlation.
- `ols.v1` — simple ordinary least-squares regression.

The live registry still omits p-values, hypothesis tests, and confidence-interval methods.

## Governed uncertainty foundation

`calyx-scientific-uncertainty/v1` introduces the first external numerical-library primitive under SCICOMP-001J/K.

The current bounded primitive computes a classical two-sided Student-t confidence interval for a population mean using:

```text
sample mean ± t_(1-alpha/2, n-1) × sample_sd / sqrt(n)
```

Implementation rules:

- confidence level must be declared before execution;
- current supported levels are 0.90, 0.95, and 0.99;
- inputs are validated before any numerical-library call;
- only `scipy.stats.t.ppf` is used for the Student-t critical value;
- raw SciPy result objects are never exposed;
- exact SciPy version is recorded in the normalized output;
- no p-value is generated;
- no interpretation or significance verdict is generated;
- human scientific review remains required;
- `analysis_plan_method_registered` remains false.

### Numerical dependency isolation

The Scientific Analysis workflow validates the primitive on Python 3.12 with `scipy==1.18.0`. SciPy resolves NumPy as its dependency in the validation environment.

SciPy is deliberately **not** added to repository-global `requirements.txt` in this slice. The repository has not yet demonstrated an authoritative production Python 3.12 pin, while SciPy 1.18.0 requires Python >=3.12. This prevents a reference-validation experiment from silently becoming a production startup dependency.

### Independent reference fixtures

The uncertainty regression suite uses published NIST/SEMATECH Dataplot confidence-limit examples as independent numerical oracles.

Reference A:

- n = 195;
- sample mean = 9.26146;
- sample SD = 0.02278;
- expected 95% t critical value ≈ 1.972;
- expected lower = 9.25824;
- expected upper = 9.26467.

Reference B:

- n = 10;
- sample mean = 0.99800;
- sample SD = 0.00434;
- expected 95% t critical value ≈ 2.262;
- expected lower = 0.99489;
- expected upper = 1.00110.

Tests use explicit floating-point tolerances and exact degrees-of-freedom checks.

Failure fixtures cover insufficient sample size, unsupported confidence levels, negative sample SD, booleans, and non-finite values. Failures surface stable CALYX uncertainty errors rather than uncaught SciPy exceptions.

### Conversational-analysis compatibility boundary

A separate open Calyx conversational-analysis branch currently offers a mean confidence interval using a normal approximation for sample sizes as small as two observations.

That is not equivalent to this Research Station Student-t uncertainty contract. A conversational confidence-interval result must therefore not be treated as the canonical research-grade CALYX interval unless it delegates to the governed Scientific Computing method. Otherwise it must remain explicitly labeled approximation-only.

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

## Checksum-bound analysis dataset snapshots
`calyx-scientific-dataset-snapshot/v1` closes the manual row-transfer gap between a registered Research Station dataset and the Analysis Workbench without creating a second dataset registry.

A snapshot may be persisted only for an existing project-scoped Research Station dataset. The submitted exact row payload is canonicalized and hashed using the same `canonical_rows_sha256` contract used during dataset registration. Persistence fails closed unless the row hash exactly equals the registered dataset checksum.

The service applies bounded private storage limits:

- maximum rows inherit the Scientific Analysis engine row limit;
- maximum columns inherit the engine column limit;
- canonical JSON payload is capped at 5 MB in this slice;
- every row must be an object;
- owner/project/dataset scope is enforced before read or write.

The immutable snapshot records dataset ID/title, registered checksum, row checksum, row/column counts, column names, encoded JSON size, exact rows, registered dataset provenance, snapshot provenance, authenticated recorder identity, and recorded time. Replaying identical rows is idempotent; conflicting content fails closed.

Snapshot listing deliberately omits row payloads. Exact rows are returned only by an explicit protected dataset-snapshot GET. This permits the Workbench to show/select lightweight metadata before retrieving scientific data.

Protected routes:

```text
GET  /brain/mission-control/research/analysis/projects/{project_id}/dataset-snapshots
GET  /brain/mission-control/research/analysis/projects/{project_id}/dataset-snapshots/{dataset_id}
POST /brain/mission-control/research/analysis/projects/{project_id}/dataset-snapshots/{dataset_id}
```

The snapshot object has no interpretation, publication, Knowledge Graph mutation, deployment, or arbitrary-code authority.

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

A dataset snapshot adds a prior transport-level assertion: the rows retrieved by the Workbench already match the registered raw dataset checksum before plan validation begins.

## Downstream artifacts
`calyx-scientific-diagnostics/v1` creates immutable descriptive diagnostic payloads bound to exact plan/analysis/input/result identity. `calyx-scientific-comparison/v1` compares runs without selecting a winner. `calyx-scientific-result-artifact/v1` provides normalized result tables and diagnostic-backed figure specifications. Diagnostics, comparisons, tables, figure specifications, and uncertainty outputs remain distinct from scientific interpretation.

## Research Station notebook integration
Successful plan execution writes a machine-readable, non-interpretive receipt into the project notebook. The receipt includes raw/pre-filter/post-filter checksums, transformation receipts, filter receipt, analysis/result identity, warnings, and governance state. Replay is idempotent and conflicting content fails closed rather than rewriting history.

## Front-end contract
The Research Station Workbench can enumerate, create, and load checksum-bound dataset snapshots. Guided controls author the same Analysis Plan fields exposed by Advanced JSON.

Before execution the Workbench shows dataset identity, source/derived variables and units, transformations, row filters with reason codes, method/rationale, and validation blockers. It must continue to avoid unlabeled outlier removal, significance color coding, or automatic method selection.

A future live mean-confidence-interval surface should show the estimate, interval, confidence level, assumptions, numerical provenance, and review status without converting interval overlap/non-overlap into an automatic scientific conclusion.

## Governance
Permanent current-slice boundaries:

- no arbitrary Python/R/shell/SQL/JavaScript execution;
- no autonomous model selection;
- no autonomous scientific publication;
- no Knowledge Graph mutation;
- no fabricated significance;
- no p-values in the uncertainty foundation;
- no live confidence-interval Analysis Plan method yet;
- no production SciPy dependency yet;
- no silent conversion of missing values to zero or absence;
- no source-column mutation by transforms;
- no undeclared/unversioned transformations;
- no free-form filter expressions;
- no implicit outlier removal;
- no anonymous excluded rows;
- every filter requires a reason code;
- dataset snapshots require exact registered checksum identity;
- snapshot storage is private and bounded;
- diagnostics are descriptive, not inferential verdicts;
- comparisons do not select a winner;
- figure specs are rendering instructions, not interpretations;
- no silent conversion of computed output into scientific interpretation;
- human review remains required before scientific conclusions become reviewed claims.

## Validation
The uncertainty implementation head successfully installed SciPy 1.18.0 on Python 3.12, compiled the new and existing scientific surfaces, passed 39 deterministic tests including both NIST references and uncertainty failure fixtures, and passed permanent governance assertions. Its only failure was Ruff `UP035` for importing `Iterable` from `typing`; that one-line import was corrected by moving `Iterable` to `collections.abc`.

Exact-head validation of the Ruff-corrected/documented branch remains the completion gate for this slice.

Earlier CALYX-617 slices retain coverage for exact registered checksum binding, replay idempotence, checksum mismatch failure, snapshot transport, explicit filters, derived-variable transforms, before/after hashes and counts, excluded-row identity/reasons, zero-row fail-closed behavior, legacy free-text exclusion rejection, replay-safe notebook receipts, diagnostics, comparison, result artifacts, and Research Station regressions.

## Next implementation priorities

1. complete exact-head validation of the uncertainty foundation;
2. explicitly establish the production Python runtime before adding SciPy to production dependencies;
3. reconcile conversational mean-CI behavior with the governed Student-t contract;
4. only after those gates, register a bounded mean-confidence-interval Analysis Plan method and normalized result artifact;
5. add Workbench estimate/interval rendering without significance color coding;
6. then consider OLS coefficient standard errors/confidence intervals under the same numerical-reference contract;
7. introduce p-values/hypothesis tests only through SCICOMP-001J method-specific governance;
8. only later design a separately sandboxed Python/R execution environment.

## Relationship impact

```text
Research Project
  -> Registered Raw Dataset + checksum
  -> Optional checksum-bound private row snapshot
  -> Typed Variables + Units
  -> Immutable Analysis Plan
  -> Raw Dataset Verification
  -> Versioned Derived-Variable Transformations
  -> Pre-filter Analytical Dataset + checksum
  -> Governed Row Filters + exclusion receipt
  -> Final Analytical Dataset + checksum
  -> Analysis Run
  -> Diagnostic / Uncertainty Artifact
  -> Result Table + Figure Specifications
  -> Optional Run Comparison
  -> Research Station Notebook / Workbench
  -> Candidate Interpretation
  -> Human Review
```

No new scientific fact is created merely because a dataset snapshot, analysis, exclusion receipt, diagnostic, uncertainty interval, comparison, table, or figure specification exists.
