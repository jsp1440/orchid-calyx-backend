# RS-12 through RS-15 — Calyx Source Workflow Handoff

Date: 2026-08-08

## Purpose

Record the validated Research Station source-workflow milestones that depend on CALYX-639/CALYX-640 and preserve the exact validation boundary for RS-15 so future autonomous work does not treat an unexecuted hosted CI gate as green.

## Validated milestones

### RS-12 — Save governed Calyx source to project

- Frontend PR #14.
- Explicit save action is available only when persisted CALYX-639 result/document identity exists.
- Browser sends relationship intent only; project/document/revision identity remains backend authority.
- Saving refreshes project document links and does not silently change active retrieval scope.
- Implementation and documentation-final Research Station CI passed formatting, lint, full tests, and production build.

### RS-13 — Reopened conversation source navigation

- Frontend PR #15.
- Persisted CALYX source refs are shown with originating conversation context.
- Historical refs without exact document identity remain metadata-only.
- Exact linked sources may be explicitly selected as next-question document scope; selection alone does not run retrieval.
- Implementation and documentation-final Research Station CI passed formatting, lint, full tests, and production build.

### RS-14 — Governed Calyx Source Archive

- Frontend PR #16.
- Project-level source archive reconstructs only source refs already persisted in owner-scoped Calyx conversations.
- Archive preserves conversation/message origin plus document/revision/identifier/locator metadata.
- Save-to-project reuses CALYX-640 and requires exact result/document identity.
- No external page fetch, fuzzy identity resolution, publication, or Knowledge Graph mutation was added.
- Implementation exact head `a7216936cb0e83dae2061251ff642514647a9c06` and documentation-final head `6c0a208933ed9c7dc7a59901d175514a0359b2cc` both passed the complete Research Station CI gate.

## RS-15 — bounded source archive pagination

Frontend PR #17 remains DRAFT.

Delivered runtime behavior:
- fixed page size of 10 conversations;
- one bounded conversation-list request per page;
- at most 10 owner-scoped conversation-detail reads for the current page;
- negative, oversized, and misaligned positive offsets normalize to a valid page boundary;
- explicit newer/older navigation;
- current conversation range, total conversation count, and current-page source count are displayed;
- project document links remain independently loaded and refresh only after an explicit save;
- all RS-14 provenance and non-authority rules remain unchanged.

Additional hardening and supplemental validation:
- manual diff review completed;
- React document-loading effect was made self-contained to avoid an ambiguous hook dependency;
- focused pagination tests cover first page, final partial page, oversized offset, negative offset, empty archive, and misaligned positive offsets;
- earlier pure pagination invariants were independently exercised across 42,220 boundary/randomized cases with zero failures after page-boundary normalization;
- on 2026-08-08 at approximately 18:59 PT, the actual `calyxSourceArchive.ts` helper was reconstructed from the PR head and compiled successfully with `tsc 5.8.3 --strict` against the imported conversation-type contract;
- the emitted JavaScript then passed 263,304 boundary/property cases plus a source-archive filtering smoke case, covering empty totals, partial final pages, negative/oversized/misaligned offsets, varying page sizes, page alignment, bounded ranges, and deterministic newer/older offsets;
- the first local compile attempt failed only because the container lacks `@types/node` for a Node-typed harness; separating the production helper compilation from the Node harness produced a clean strict-TypeScript compile and runtime result;
- this supplemental validation is materially stronger than manual inspection but is not a substitute for the repository's full formatting/lint/Vitest/production-build gate.

## Current validation blocker

Beginning with RS-15, GitHub-hosted Research Station jobs repeatedly fail before workflow step 1. The observed job objects contain `steps: null`; there are no formatter, lint, test, build, or application-step failures and no retrievable project log. Fresh heads and explicit reruns reproduce the same pre-step termination. The latest explicit RS-15 rerun at approximately 18:59 PT again produced a failed `validate` job with no steps.

The failure is confirmed cross-repository and outside the RS-15 changed surface:
- RS-15 changes exactly four files: its documentation, the source archive component, the pagination helper, and focused pagination tests; no `.github/workflows/*` file changed relative to last-green RS-14;
- `orchid-calyx-backend` independent CALYX-640, Mission Control registration, governance, Brain autonomy, University migration, and agent workflows reproduce `steps: null` before checkout/setup;
- an isolated diagnostic workflow on explicit `ubuntu-22.04` failed before step 1;
- a diagnostic `ubuntu-latest` workflow containing exactly one shell `echo` step and no checkout, language setup, dependencies, services, secrets, or application code failed before step materialization;
- a separate `ubuntu-slim` one-step smoke workflow failed the same way;
- a cross-platform private-repository probe on `orchid-calyx-backend` failed before step 1 on both `ubuntu-22.04` and `windows-2022`;
- the same two-platform probe on the private `Orchid-Continuum-Brain` repository also failed before step 1;
- the same Ubuntu + Windows probe on the public `orchid-continuum-frontend` repository executed successfully, including checkout and echo steps.

The controlled public/private comparison rules out a GitHub-wide hosted-runner outage, account-wide inability to allocate hosted runners, backend-only workflow code, Linux/PostgreSQL, `ubuntu-latest` aliasing, and a backend-repository-only policy as the immediate cause. The failure follows private repositories under the personal account.

Repository metadata confirms these private repositories are owned by the personal GitHub user account `jsp1440`, not an organization. Organization-level runner groups therefore do not apply as the immediate cause.

GitHub's current Actions billing model is consistent with the observed public/private split: standard hosted runners are free for public repositories, while private-repository hosted jobs consume the owner's included or paid Actions allowance. If included usage is exhausted without an available paid path, or an Actions budget is configured to stop usage at its limit, private hosted jobs can be blocked. Included-usage alert emails are configurable, so the absence of a 90%/100% warning in the connected mailbox does not exclude quota or budget exhaustion.

Canonical infrastructure incident: `orchid-calyx-backend` issue #481.

Do not label this as an application-code failure, and do not promote RS-15 to review-ready until an executable full Research Station gate succeeds.

## Administrative recovery criteria

The connected GitHub app can inspect workflow runs/jobs and request reruns but does not expose the personal-account Actions usage, budget, payment, or repository Actions settings required to repair this boundary. Recovery requires checking the personal GitHub account/repository UI for:
1. current GitHub Actions included usage for this billing cycle;
2. whether a valid payment method is present if included minutes are exhausted;
3. Actions budgets/spending controls, especially any exhausted budget with `Stop usage when budget limit is reached` enabled;
4. repository Settings → Actions → General to confirm private-repository Actions remain enabled;
5. the failed workflow-run summary for a billing, spending, private-repository, or allocation annotation omitted from the Jobs API.

A single private-repository job obtaining a runner and exposing real workflow steps is the recovery signal. Once that happens, RS-15 must be re-run unchanged before any further source-archive feature is stacked.

## Governance boundary

Across RS-12 through RS-15:
- conversation text remains `CONVERSATION_CONTEXT`, not evidence;
- source refs remain provenance pointers to governed Continuum material;
- no scientific publication is authorized;
- no Knowledge Graph mutation is authorized;
- no production deployment or merge is authorized by this record;
- enabling paid GitHub Actions overage, adding/changing a payment method, or increasing a hard-stop Actions budget is an owner financial/administrative decision and is outside autonomous application-code authority.

## Next action

1. Keep RS-15 PR #17 draft while private hosted CI cannot execute.
2. Inspect the personal-account Actions usage/payment/budget controls above.
3. If usage is blocked by quota/budget, owner decides whether to wait for the billing-cycle reset or explicitly enable paid overage/increase the Actions budget.
4. When a private-repository runner becomes executable, run the unchanged full Research Station gate first.
5. Fix any real project-stage failure before expansion.
6. Promote RS-15 only after an exact-head green gate.
7. Only then consider deterministic archive filtering or a separately governed canonical document-read surface.
