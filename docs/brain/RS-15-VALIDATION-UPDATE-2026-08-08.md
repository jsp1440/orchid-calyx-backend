# RS-15 Validation Update — 2026-08-08 20:11 PT

## Scope

This record supplements `RS-12-15-CALYX-SOURCE-WORKFLOW-HANDOFF.md` and captures the exact RS-15 runtime hardening, supplemental validation, and private-repository CI boundary.

## Current Research Station state

- PR: `jsp1440/orchid-research-station#17` — RS-15 bounded Calyx Source Archive pagination.
- Base: `feature/research-calyx-source-archive-14`.
- PR remains draft, mergeable, unmerged, and non-production.
- Latest runtime head: `7ac7fc430ec1518b91e8c8d4eca3e43ddd597238`.
- Previous runtime sequencing head: `95ce5ba76d8ebd09decb1430760197824e4ac1d9`.
- Frontend documentation is tracked separately from runtime behavior and must not be treated as runtime validation.

## Runtime corrections completed

A deeper component review identified and closed multiple related UI-state correctness risks in the independently loaded project-document-link and conversation-page state.

### 1. Independent error state

Project document-link loading and paginated conversation loading no longer share one error channel. A conversation-page load cannot silently clear a document-link failure that affects saved-source state.

### 2. Fail closed when project-link state is unknown

An empty local document array is not treated as equivalent to a successfully loaded project with zero links. Exact source-save actions remain disabled until authoritative project-link state has loaded. The UI reports `Checking project links…` while pending and `Project links unavailable` after failure, with an explicit bounded retry action.

### 3. Accurate partial-success reporting

Source linking and its follow-up project-link refresh are separate operations. If CALYX-640 saves the source but the refresh fails, the UI reports `saved, refresh failed` rather than falsely reporting the source save itself as failed.

### 4. Stale-project isolation

Async save/refresh completions are guarded by the originating project ID. A stale Project A operation cannot overwrite Project B document state, notices, errors, or save-state cleanup after navigation.

### 5. Newest-request-wins document-link sequencing

Runtime head `95ce5ba76d8ebd09decb1430760197824e4ac1d9` adds a monotonic document-request sequence. Only the newest project-link request for the active project may update authoritative document state. If two retries overlap, an older success or failure is ignored after a newer request has begun.

The same head adds a synchronous `savingKeyRef` guard so rapid repeated clicks cannot start duplicate source-link requests during the interval before React state rerenders. The backend remains idempotent, but the frontend no longer relies on backend idempotence to compensate for the pre-render duplicate-submit window.

### 6. Project-scoped pagination reset

Runtime head `7ac7fc430ec1518b91e8c8d4eca3e43ddd597238` resets conversation offset, total, and loaded conversation details whenever `projectId` changes. Project B therefore opens at its newest page instead of inheriting an older-page offset from Project A. This also prevents stale Project A counts/details from being treated as Project B pagination state during the transition.

These changes do not alter source identity, provenance authority, conversation evidence status, publication authority, or Knowledge Graph mutation authority.

## Supplemental validation completed

While private hosted runners remain unavailable:

- manual PR-diff and async-flow review completed;
- focused pagination tests cover first page, final partial page, oversized offset, negative offset, empty archive, and misaligned positive offsets;
- earlier pagination property validation passed 42,220 cases after page-boundary normalization;
- the actual `calyxSourceArchive.ts` helper compiled successfully with `tsc 5.8.3 --strict` against the imported conversation contract;
- emitted helper JavaScript passed 263,304 boundary/property cases plus source-archive filtering smoke coverage;
- the corrected `CalyxSourceArchive.tsx` integration surface was reconstructed against the real internal conversation, source-identity, document-scope, conversation-client, and Research Workspace link signatures;
- the independent-error-state and fail-closed/stale-project-guard revisions passed strict TypeScript integration compilation;
- subsequent static state-machine review identified and closed the overlapping-retry race, pre-rerender duplicate-save window, and inherited cross-project conversation offset;
- a final 20:11 PT state-machine audit of the current runtime file found no additional defect that justified another application-code change within RS-15 scope.

These supplemental checks do not replace canonical repository formatting, lint, Vitest, and production-build validation.

## Private Actions blocker remains active

Private-repository Research Station CI still fails before project code is reached.

Recent exact runtime heads:

- `a338aa676d879b19a83069dc36a88057cd091a8a`: independent document-error channel; run `31290518440`, job `93186733706`, `steps: null`;
- `45c7250bfc40f86b279152011ded94bdafc31902`: fail-closed project-link state and accurate partial-success reporting; run `31290965679`, job `93187920005`, `steps: null`;
- `ccd53a40af6b62d4182c3e2bedecacdbaee39e45`: stale-project async guards plus retry; run `31291028502`, job `93188099034`, `steps: null`;
- `95ce5ba76d8ebd09decb1430760197824e4ac1d9`: newest-request-wins sequencing and synchronous save serialization; run `31291445521`, job `93189218483`, `steps: null`;
- `7ac7fc430ec1518b91e8c8d4eca3e43ddd597238`: project-boundary pagination reset; run `31291482856`, job `93189329579`, `steps: null`;
- frontend documentation head `e4a6513556653d60dae957db286751e5fc816bf2`: run `31291506072`, job `93189396932`, also failed before step 1 with `steps: null`.

No checkout, formatting, lint, test, build, or application step executed on those failed runs.

Canonical incident #481 now also records a fresh-`main` private backend successor whose dedicated migration-runner and governance workflows fail before checkout. That independent reproduction rules out stale branch history and explicitly concludes that further application commits or blind CI retries are not productive until a private-repository workflow obtains real steps or the personal-account Actions administrative state is inspected.

Controlled diagnostics remain decisive:

- public `jsp1440/orchid-continuum-frontend` executes equivalent Ubuntu and Windows hosted-runner probes;
- private `jsp1440/orchid-calyx-backend` fails those probes before step 1;
- private `jsp1440/Orchid-Continuum-Brain` fails those probes before step 1.

The failure follows private repositories under the personal account rather than RS-15 code, one repository workflow, Linux, Windows, checkout, language setup, or GitHub-hosted runners generally. Canonical infrastructure incident remains backend issue #481.

## Governance boundary

Do not:

- mark RS-15 review-ready before an exact-head full Research Station gate executes successfully;
- merge or deploy RS-15;
- make a private repository public as a CI workaround;
- enable paid Actions overage, change a payment method, or increase a hard-stop Actions budget without owner decision;
- interpret conversation text as evidence or authorize scientific publication / Knowledge Graph mutation through this work;
- add further RS-15 application commits solely to probe a pre-step runner-allocation failure.

## Recovery sequence

1. Restore private-repository hosted Actions execution at the account/repository administrative layer.
2. Treat any private-repository job with materialized workflow steps as the recovery signal.
3. Run unchanged runtime head `7ac7fc430ec1518b91e8c8d4eca3e43ddd597238` through the complete Research Station formatting/lint/Vitest/production-build gate.
4. Fix any real project-stage failure before expanding scope.
5. Promote PR #17 only after one exact runtime head is fully green.
6. Only then proceed to RS-16 or another source-archive capability.
