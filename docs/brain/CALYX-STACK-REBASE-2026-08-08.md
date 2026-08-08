# CALYX stacked dependency rebase and exact-head validation — 2026-08-08

## Scope

This Brain record documents recovery of the CALYX Literature Intelligence → Research Station → Scientific Computing dependency stack after `main` advanced and the original stacked heads became non-mergeable.

No scientific publication, production deployment, Knowledge Graph mutation, or merge was performed by this recovery work.

## CALYX-448 Literature Intelligence

Canonical PR: #601 (`feature/calyx-literature-acquisition-448`).

The original branch had valid focused checks but had drifted from current `main` and became non-mergeable. A scratch branch was reconstructed from current `main`, preserving the six CALYX-448 files and integrating the Literature router into the current Mission Control router instead of overwriting later Mission Control work.

Validation exposed one Ruff UP037 annotation regression in the reconstructed runtime. The annotation was corrected rather than suppressing the rule.

Validated canonical head: `261c43512197b5ab5d1884b4a210227ca63ba01c`.

Exact-head validation passed:

- CALYX Literature Acquisition 448: compile, 22 focused/regression tests, permanent non-authority assertions, Ruff, diff hygiene;
- CALYX Workflow Governance Audit;
- BUILD-088E Validation;
- CALYX-SUPERVISED-PILOT-001;
- CALYX-AUTONOMY-DEPLOYMENT-001.

The canonical branch was advanced to the validated head and PR #601 moved from draft to ready-for-review. External Greptile review did not run because that trial account reported its credit limit reached; no code-review findings were returned.

## CALYX-453 Research Station

Canonical PR: #606 (`feature/calyx-research-station-453`), stacked on CALYX-448.

After CALYX-448 was rebased, the old #606 head became non-mergeable because it still carried the prior Literature base. Recovery used Git object identity rather than textual reconstruction: the five Research Station implementation blobs were reused byte-for-byte from the prior canonical head, while `app/routers/live_mission_control.py` was integrated against the newly validated Literature base so both route families remain registered.

Validated canonical head: `3cde9f7b34a282b84d65bd3e7bb8a2e549e0145a`.

Exact-head validation passed:

- CALYX Research Station 453;
- upstream CALYX Literature Acquisition 448 regression lane;
- CALYX Workflow Governance Audit;
- CALYX-SUPERVISED-PILOT-001;
- CALYX-AUTONOMY-DEPLOYMENT-001.

The canonical branch was advanced to the validated head and PR #606 moved from draft to ready-for-review.

## CALYX-617 Scientific Computing & Analysis Engine

Canonical PR: #618 (`feature/calyx-scientific-analysis-617`), stacked on CALYX-453.

The CALYX-617 rebase identified an intentional upstream integration change in `runtime/research_station.py`: Literature Intelligence is lazy-loaded so the analysis workflow can depend on Research Station without creating an import cycle. The exact 17-file CALYX-617 delta was reused from the prior canonical head on top of validated CALYX-453. Upstream Literature payload was not duplicated.

Validated pre-documentation head: `edab7bf0aad285b8427959f5792eca036a850e0d`.

Exact-head validation passed six lanes:

- CALYX Scientific Analysis 617;
- CALYX Research Station 453 regression lane;
- CALYX Literature Acquisition 448 regression lane;
- CALYX Workflow Governance Audit;
- CALYX-SUPERVISED-PILOT-001;
- CALYX-AUTONOMY-DEPLOYMENT-001.

The canonical branch was advanced to that validated implementation head and PR #618 moved from draft to ready-for-review.

## Research Station frontend Workbench

Repository: `jsp1440/orchid-research-station`.
Canonical PR: #5 (`feature/research-analysis-workbench-4`).

The frontend Workbench consumes the governed CALYX-617 plan/validate/execute/diagnostic/result-artifact contracts. Its current CI head `9a9d61d82c065f4e2aca55f66cd02ab5f5be05ea` passed the repository CI workflow and the PR is mergeable. After the backend contract stack was rebased and validated, frontend PR #5 moved from draft to ready-for-review.

The Workbench remains non-production and retains the documented transitional manual JSON row transport until a governed registered-dataset row retrieval API replaces it.

## Governance boundary

All three backend PRs explicitly preserve no-merge/no-production-authority boundaries, and the frontend PR explicitly forbids production deployment. Therefore this recovery stops short of merging or deploying the stack even though implementation and exact-head validation are green.

A future authorized merge should preserve dependency order:

1. #601 into `main`;
2. retarget/merge #606 after #601 lands;
3. retarget/merge #618 after #606 lands;
4. merge/deploy frontend #5 only after the backend API contract is available in the intended environment and frontend review gates remain green.

Temporary scratch PRs #627, #629, and #630 were created only as exact-head validation surfaces and should remain unmerged/closed after canonical branch promotion.
