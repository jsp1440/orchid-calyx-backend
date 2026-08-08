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
- stale/negative offsets clamp to a valid page;
- explicit newer/older navigation;
- current conversation range, total conversation count, and current-page source count are displayed;
- project document links remain independently loaded and refresh only after an explicit save;
- all RS-14 provenance and non-authority rules remain unchanged.

Additional hardening:
- manual diff review completed;
- React document-loading effect was made self-contained to avoid an ambiguous hook dependency;
- focused pagination tests cover first page, final partial page, oversized offset, negative offset, and empty archive.

## Current validation blocker

Beginning with RS-15, GitHub-hosted Research Station jobs repeatedly fail before workflow step 1. The observed job objects contain `steps: null`; there are no formatter, lint, test, build, or application-step failures and no retrievable project log. Fresh heads and explicit reruns reproduce the same pre-step termination.

At 2026-08-08 15:30 PT the latest rerun still failed before step 1. The exact external cause is not established from available repository APIs. Do not label this as an application-code failure, but do not promote RS-15 to review-ready until an executable full Research Station gate succeeds.

## Governance boundary

Across RS-12 through RS-15:
- conversation text remains `CONVERSATION_CONTEXT`, not evidence;
- source refs remain provenance pointers to governed Continuum material;
- no scientific publication is authorized;
- no Knowledge Graph mutation is authorized;
- no production deployment or merge is authorized by this record.

## Next action

1. Keep RS-15 PR #17 draft while hosted CI cannot execute.
2. When an executable runner becomes available, run the unchanged full Research Station gate first.
3. Fix any real project-stage failure before expansion.
4. Promote RS-15 only after an exact-head green gate.
5. Only then consider deterministic archive filtering or a separately governed canonical document-read surface.
