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
- pure pagination invariants were independently exercised across 42,220 boundary/randomized cases with zero failures after page-boundary normalization;
- this supplemental property check verifies page alignment, bounded ranges, correct final partial pages, and deterministic newer/older offsets, but it is not a substitute for the repository's full TypeScript/lint/test/build gate.

## Current validation blocker

Beginning with RS-15, GitHub-hosted Research Station jobs repeatedly fail before workflow step 1. The observed job objects contain `steps: null`; there are no formatter, lint, test, build, or application-step failures and no retrievable project log. Fresh heads and explicit reruns reproduce the same pre-step termination.

The failure is confirmed cross-repository and outside the RS-15 changed surface:
- RS-15 changes exactly four files: its Brain/doc record, the source archive component, the pagination helper, and focused pagination tests; no `.github/workflows/*` file changed relative to last-green RS-14;
- `orchid-calyx-backend` independent CALYX-640, Mission Control registration, governance, Brain autonomy, University migration, and agent workflows reproduce `steps: null` before checkout/setup;
- an isolated diagnostic workflow on explicit `ubuntu-22.04` failed before step 1;
- a diagnostic `ubuntu-latest` workflow containing exactly one shell `echo` step and no checkout, language setup, dependencies, services, secrets, or application code failed before step materialization;
- a separate `ubuntu-slim` one-step smoke workflow failed the same way;
- the latest Research Station retries and newer backend heads continue to return `steps: null`.

This evidence rules out RS-15 application code, the Research Station workflow diff, checkout/setup actions, Python/PostgreSQL startup, `ubuntu-latest` aliasing, and a full-VM-only runner image as the immediate failure source.

Repository metadata further narrows the administrative boundary: both repositories are owned by the personal GitHub user account `jsp1440`, not an organization. Organization-level runner groups or organization-hosted-runner disablement therefore do not apply to these repositories as the immediate cause.

GitHub's current Actions billing documentation states that private-repository GitHub-hosted jobs consume the repository owner's account allowance. If the included Actions quota is exhausted and the account has no valid payment method, hosted usage is blocked. GitHub also documents that an exhausted Actions budget configured to stop usage blocks further hosted-runner use. Included-usage alert emails are configurable, so the absence of a 90%/100% warning in the connected mailbox does not exclude quota or budget exhaustion.

Canonical infrastructure incident: `orchid-calyx-backend` issue #481.

Do not label this as an application-code failure, and do not promote RS-15 to review-ready until an executable full Research Station gate succeeds.

## Administrative recovery criteria

The engineering side cannot inspect personal-account billing controls through the connected repository API. Recovery now requires checking the personal GitHub account and repository UI for:
1. current GitHub Actions included usage for this billing cycle;
2. whether a valid payment method is present if included minutes are exhausted;
3. Actions budgets/spending controls, especially any exhausted budget with `Stop usage when budget limit is reached` enabled;
4. repository Settings → Actions → General to confirm Actions remain enabled;
5. the failed workflow-run summary for a billing, spending, or allocation annotation omitted from the Jobs API.

A single job obtaining a runner and exposing real workflow steps is the recovery signal. Once that happens, RS-15 must be re-run unchanged before any further source-archive feature is stacked.

## Governance boundary

Across RS-12 through RS-15:
- conversation text remains `CONVERSATION_CONTEXT`, not evidence;
- source refs remain provenance pointers to governed Continuum material;
- no scientific publication is authorized;
- no Knowledge Graph mutation is authorized;
- no production deployment or merge is authorized by this record;
- enabling paid GitHub Actions overage, adding/changing a payment method, or increasing a hard-stop Actions budget is an owner financial/administrative decision and is outside autonomous application-code authority.

## Next action

1. Keep RS-15 PR #17 draft while hosted CI cannot execute.
2. Inspect the personal-account Actions usage/payment/budget controls above.
3. If usage is blocked by quota/budget, owner decides whether to wait for the billing-cycle reset or explicitly enable paid overage/increase the Actions budget.
4. When an executable runner becomes available, run the unchanged full Research Station gate first.
5. Fix any real project-stage failure before expansion.
6. Promote RS-15 only after an exact-head green gate.
7. Only then consider deterministic archive filtering or a separately governed canonical document-read surface.
