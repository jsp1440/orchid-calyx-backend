# Execution-cost pricing and the OC-EVALS-001 deterministic evaluation layer

Status: draft implementation record. Branch `claude/orchid-brain-efficiency-qgbdm7`; this continues draft PR #1814.
Specification implemented: Brain `14_ENGINEERING/OC-EVALS-001-self-improving-agent-evaluation-blueprint.md`. EVALS-001A contracts, EVALS-001B deterministic harness, first slice of EVALS-001D.
Companion records (Brain PR #252): BRAIN-EFFICIENCY-002 (tooling comparison) and KG-BITEMPORAL-001 (proposal only).

Nothing here adds a scheduler, queue, database or paid service. Nothing touches the autonomy-recovery files in #1806 and #1795: `swarm_governor_postrun.py`, `runtime/swarm/governor.py`, `oc_swarm_settlement.py` and `orchid-completion-lane.yml`.

## 1. Execution-cost pricing

| Piece | Path |
|---|---|
| Versioned price table | `config/provider-pricing-v1.json`. Schema `oc.provider-pricing.v1`, version `2026-10-13.1`, sourced from the Anthropic pricing page retrieved on 2026-10-13. |
| Pricing (pure, stdlib only) | `runtime/swarm/pricing.py` |
| Receipt integration | `scripts/swarm_anthropic_direct.py`: `requestUsage` (per turn) and `cost` (`oc.execution-cost.v1`) in the execution result and `[OC-DIRECT-RECEIPT]`. `estimated_cost_usd`, `cost_basis` and `pricing_version` in GitHub outputs. |
| Re-price / verify CLI | `scripts/oc_execution_cost.py --execution-file … [--verify]` |

### Estimate vs. billed

- **`basis` is always `list_price_estimate` or `unavailable`.** `billed_usd` stays `null` and `billed_basis` says why: the Messages API does not return a billed cost per request.
- **`total_cost_usd` stays `null`.** The lane's classifier is unchanged.
- **`OC_GOVERNOR_ACTUAL_COST_USD` must not receive the estimate.** The governor treats that variable as billed spend. Wiring the estimate into post-run as a separately labelled source is left to the autonomy-recovery owners, because that file is theirs.
- **`TaskEconomics` keeps the distinction.** The estimate maps to `estimated_cost_usd`; `actual_cost_usd` stays `None`, so `cost_per_completed_task` stays unknown. This is tested.

### Rules
- **Prices per request.** Some rates depend on prompt length, and cache reads and writes count toward it. Haiku 5.5, for example, has a higher rate above 100k prompt tokens. Pricing run totals would therefore be wrong; the executor records per-turn usage and prices each turn.
- **Cache-aware.** 5-minute and 1-hour writes are priced separately when the usage breakdown is present. Without the breakdown they are priced as 5-minute, which is the executor's only TTL, and flagged `cache_write_ttl_assumed_5m`. Cache reads use each model's published multiplier: 0.1× standard, 0.05× for Opus 5.5 and Sonnet 5.5, 0.025× for Fable 5.1.
- **Unknown stays unknown.** An unlisted model, fast mode, a batch or priority tier, an unknown `inference_geo`, or malformed usage leaves `estimated_usd` as `null` and `complete` as `false`, with reasons. The priced subtotal is reported, labelled as incomplete.
- **Applies the US-inference multiplier** of 1.1× where `inference_geo = "us"` on 4.6+ models only.
- **Matches model ids exactly**, or through a declared alias such as `claude-sonnet-4-20250514`. It never uses prefix matching.
- **Pricing can never fail a run.** A missing or invalid table produces a cost block with `basis = "unavailable"`.
- **A price change is a new table version.** Receipts keep the version they were priced with; verification against a different version is reported, never silently recomputed.

## 2. OC-EVALS-001 deterministic evaluation layer (`runtime/evals/`)

| Module | Blueprint part |
|---|---|
| `contracts.py` | EVALS-001A: `EvaluationTaskClass`, `StrategySpec` (provenance fingerprint), `EvaluationCase`, `EvaluationRun`, `EvaluationResult`, `StrategyDecision` (the blueprint's nine decision values), and `MeasurementState` (`MEASURED` / `UNMEASURED` / `PARKED`) |
| `evaluators.py` | EVALS-001B: deterministic evaluators |
| `runner.py` | EVALS-001B: fixture-backed, idempotent runs, NO_API_MODE parking |
| `decision.py` | EVALS-001D (first slice): promotion gate, JSON suppression ledger, memory summary, active-strategy resolution |
| `deepeval_adapter.py` | Optional DeepEval compatibility (no LLM judge) |
| `fixtures.py`, `scripts/oc_evals_run.py` | Fixture loader and offline CLI |

### Evaluators (all provider-free)

| Metric | Gate | Checks |
|---|---|---|
| `test_outcomes` | | Required checks passed **on the output's head**. A pass recorded against another commit does not count. |
| `scope_compliance` | yes | Changed paths stay within the case scope. None of them are protected (executor protected set, governance paths, workflows, `runtime/swarm/*`, env and secret files) or outside the repository. |
| `provenance_completeness` | | Full 40-hex head, branch, model usage, prompt-cache state, pricing version, per-request usage, checks, evidence. |
| `receipt_validity` | yes | Receipt structure, subtype matching `is_error`, non-negative counts, one usage entry per turn, no billed amount without a billed basis. **The cost block must recompute** under its pricing version; a different version is noted, not failed. |
| `evidence_quality` | | Every evidence item names the full output head. Abbreviated or stale SHAs fail, and required evidence kinds must be present. |

A fact the output does not contain is reported as `UNMEASURED` with `score = None`, never as zero. `rubric_judge` is declared as a provider-requiring evaluator, so the NO_API path is exercised end to end. Under NO_API_MODE it is `PARKED`, using the repository's fail-closed `oc_no_api_guard.evaluate`, where an absent value means blocked. When allowed, it still produces no score in this slice.

### Promotion gate

The checks run in this order:
1. Same frozen case set and evaluator versions.
2. Suppression of an unchanged candidate already decided.
3. Gate failure → `REJECT_SAFETY`.
4. Replicate disagreement → `REJECT_INSTABILITY`.
5. Unmeasured primary metric → `UNMEASURED`.
6. Below the quality floor, or a protected-metric regression → `REJECT_QUALITY`.
7. Improvement → `PROMOTE` (a `LIMITED_CANARY` that needs human approval for high-risk classes).
8. Equal quality at materially lower *known* cost → `PROMOTE`. An unknown cost is never a saving.
9. Costlier with no gain → `REJECT_COST`.
10. Otherwise `KEEP_BASELINE`.

Decisions carry thresholds, evidence run ids, scope, rollback target and review trigger. `authorizes` must be empty: an eval outcome never merges, deploys, publishes or activates a provider.

### Blueprint acceptance items covered offline (`tests/test_oc_evals.py`, names prefixed `a1…a12`)

1. Task classified.
2. Strategy specs frozen.
3. Same versioned cases.
4. Results with provenance. Results are reproducible JSON; durable persistence is not added (no new database).
5. Cost and latency unknowns kept unknown.
6. Policy violation rejected.
7. No-benefit candidate not promoted and suppressed on rediscovery.
8. Better candidate promoted with scope and rollback.
9. Memory summary **produced only**. It is not written into Scientific Memory (see the integration status below).
10. Active strategy **computable only**. No orchestrator calls it (see the integration status below).
11. Replay idempotent.
12. Decisions authorize nothing.

### Integration status: what is and is not operational

| Capability | State | Evidence / gap |
|---|---|---|
| Deterministic evaluators, runner, promotion gate, suppression ledger | **Implemented, offline only** | Exercised by `tests/test_oc_evals.py` and the fixture CLI. Nothing runs it on a schedule or on live executor output yet. |
| Scientific Memory write-back (blueprint acceptance 9; EVALS-001D) | **Not integrated** | `memory_summary()` returns a dict and nothing persists it. No Scientific Memory API is called, and no test proves a write. |
| Active-strategy resolution used by the orchestrator (acceptance 10; EVALS-001C) | **Not integrated** | `resolve_active_strategy()` is a pure function that no scheduler, router or orchestrator calls. `scripts/oc_model_router.py` still chooses tiers by its own rules. |
| Provider-backed (LLM-judge) evaluators | **Not implemented** | `rubric_judge` is declared only so the NO_API parking path is tested. It produces no score when allowed. |

Neither integration may be described as operational until a test proves the write-back or the orchestrator call against the real component.

## 3. Offline Promptfoo red team (`security/promptfoo/`)

- **What it tests:** 41 enforced adversarial and control tool calls against the real executor tool handlers, run in a throwaway sandbox. Commands are recorded, never run.
- **Results:**
  - pytest (`tests/test_oc_promptfoo_security_cases.py`): 41 of 41.
  - Promptfoo 0.123.1 (pinned; telemetry, sharing and updates off): **41 passed, 0 failed**.
- **Closed in the executor** (owner-authorized; commit `4fafb2f`):
  - **OC-SEC-EXEC-001:** credential files are no longer readable, searchable, writable or usable as a check target. This covers symlinks; secret-free `.env` templates stay readable.
  - **OC-SEC-EXEC-002:** every restricted governance path in `docs/AGENT-SECURITY-BOUNDARIES.md` is read-only to the executor.
  - **OC-SEC-EXEC-003** (found while closing 001): `search_text` returned the contents of a file symlinked from outside the repository.
- **Fix verified:** against the previous executor 18 cases fail; after the fix all pass. Legitimate operations are control cases: reading `AGENTS.md`, reading `.env.example`, writing `docs/AGENT-OPERATING-MEMORY.md`, and normal source edits. `gaps.yaml` is empty.

## 4. CI

`.github/workflows/oc-cost-evals-validation.yml` has three jobs. `NO_API_MODE` is forced on in all of them, no secrets are exposed, and permissions are `contents: read`.

| Job | Runs on | What it does |
|---|---|---|
| `cost-and-evals` | PRs touching these paths | Pinned `requirements-dev.txt` (ruff 0.16.8, pytest 9.1.1) plus pyyaml; compile, ruff check and format, Promptfoo config drift check, the test files, and the offline fixture CLI. |
| `deepeval-compatibility` | PRs touching these paths | `deepeval==4.2.6`, telemetry off, no judge model. |
| `promptfoo-redteam` | Manual `workflow_dispatch` only (`run_promptfoo`) | Node 22 and the pinned Promptfoo. |

## 5. Validation evidence (local, this head)

- **CI-equivalent venv** (requirements-dev plus pyyaml only; ruff 0.16.8, Python 3.13): the six CI test files give **191 passed, 5 xfailed** (the 5 open security gaps). The DeepEval adapter test is skipped without deepeval.
- **DeepEval 4.2.6 venv:** adapter tests **9 passed**, with no API keys set.
- **Wider regression run with app dependencies** (calyx_engineering, swarm governor and economy, router, NO-API guard, prompt cache, conservatory evaluations, and the new suites): **463 passed, 5 xfailed**.
- **Mutation controls,** run under `python -B -p no:cacheprovider`, with the control green before and after:

  | Mutant | Failures caught |
  |---|---:|
  | Per-request long-prompt tier removed | 1 |
  | Protected-path scope check removed | 6 |
  | Safety-gate rejection removed | 1 |
  | NO_API parking removed | 5 |

- **Hand-checked amounts:**
  - Opus 5: 1k in, 2k out, 10k 5-minute write, 100k read = $0.1675.
  - Executor e2e on Sonnet 5, two turns = $0.012400.
  - Haiku 5.5: two 60k prompts = $0.012, one 120k prompt = $0.06.
- **Fixture CLI under NO_API_MODE:** better candidate → `PROMOTE` (test outcomes 0.6250 → 1.0000); workflow-editing candidate → `REJECT_SAFETY`; Opus no-gain candidate → `REJECT_COST` (estimated $0.128850 → $0.700800 over the four cases).
- `ruff check` and `ruff format --check` clean on all new and changed files; `git diff --check` clean.

## 6. Follow-ups (not done here)

1. **Post-run wiring** (autonomy-recovery owners; coordination note posted on #1806): record `estimated_cost_usd` and `cost_basis` from the executor outputs in the governor ledger as a separately labelled estimate. It must never be passed as `OC_GOVERNOR_ACTUAL_COST_USD` or `actual_usd`, both of which mean verified billed spend.
2. **Billed reconciliation:** reconcile estimates against invoices through the Usage & Cost Admin API. This needs an admin credential, which is owner-gated.
3. **EVALS-001C:** integrate the strategy router with the canonical orchestrator. **EVALS-001D:** persist memory summaries in Scientific Memory. Both are not integrated today; see the integration status above.
4. **Scientific task classes:** literature and taxonomic extraction against the #1182 gold set, and evidence-grounded synthesis.
5. **Ruff UP017 baseline failure:** handled in a separate draft PR that pins ruff in the affected workflows (see that PR).
