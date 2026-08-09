# RS-15 Validation Update — 2026-08-08 19:40 PT

## Scope

This record supplements `RS-12-15-CALYX-SOURCE-WORKFLOW-HANDOFF.md` and captures the latest exact RS-15 runtime hardening, supplemental validation, and private-repository CI state.

## Current Research Station state

- PR: `jsp1440/orchid-research-station#17` — RS-15 bounded Calyx Source Archive pagination.
- Base: `feature/research-calyx-source-archive-14`.
- PR remains draft, mergeable, unmerged, and non-production.
- Latest runtime head: `ccd53a40af6b62d4182c3e2bedecacdbaee39e45`.
- Frontend documentation was updated after the runtime correction to record the repeated pre-step CI failures; those documentation-only commits do not alter runtime behavior.

## Runtime corrections completed

A deeper component review identified three related UI-state correctness risks in the independently loaded project-document-link state.

### 1. Independent error state

The earlier RS-15 component allowed project document-link loading and paginated conversation loading to share one `error` state. A conversation-page load could therefore clear a document-link failure even though document-link state determines whether a persisted source is already saved.

This was corrected by introducing a dedicated `documentError` channel.

### 2. Fail closed when project-link state is unknown

An empty local document array is not equivalent to a successfully loaded project with zero document links. Before the latest hardening, conversation data could render before project document links finished loading, making an already-linked exact source temporarily appear saveable.

The current implementation now:

- tracks whether project document links have loaded successfully;
- disables exact source-save actions until link state is known;
- reports `Checking project links…` while link state is pending;
- reports `Project links unavailable` when the link request has failed;
- exposes a bounded explicit `Retry project links` action after failure;
- keeps save actions disabled after a failed post-save refresh until project links load successfully again.

Backend CALYX-640 idempotence already prevents duplicate-link corruption, but the frontend now fails closed instead of relying on that backend property to compensate for uncertain UI state.

### 3. Accurate partial-success reporting and stale-project isolation

A source-link request and its follow-up project-link refresh are separate operations. If the source link succeeds but the refresh fails, reporting the entire save as failed is inaccurate and can encourage unnecessary retries.

The current implementation now reports that the governed source was saved while the project-link status refresh failed. It does not claim the save itself failed.

The component also guards asynchronous save/refresh completions by the originating project ID. If the operator navigates from Project A to Project B while a Project A operation is in flight, the stale Project A completion cannot:

- overwrite Project B document-link state;
- write a Project A notice/error into Project B;
- clear a Project B save indicator;
- re-enable save controls from stale Project A state.

Project changes clear stale local project-link state before the new project load is considered authoritative.

These changes do not alter source identity, provenance authority, conversation evidence status, publication authority, or Knowledge Graph mutation authority.

## Supplemental validation completed

While private hosted runners remain unavailable:

- manual PR-diff review completed;
- focused pagination tests cover first page, final partial page, oversized offset, negative offset, empty archive, and misaligned positive offsets;
- earlier pagination property validation passed 42,220 cases after page-boundary normalization;
- the actual `calyxSourceArchive.ts` helper compiled successfully with `tsc 5.8.3 --strict` against the imported conversation contract;
- emitted helper JavaScript passed 263,304 boundary/property cases plus source-archive filtering smoke coverage;
- the corrected `CalyxSourceArchive.tsx` integration surface was reconstructed against the real internal conversation, source-identity, document-scope, conversation-client, and Research Workspace link signatures;
- the independent-error-state version passed strict TypeScript integration compilation;
- the fail-closed plus stale-project-guard version also passed strict TypeScript integration compilation;
- static async-flow review confirms stale project completions are checked before mutating document state, notices, errors, or save-state cleanup.

The first local helper compile attempt encountered only a container fixture limitation (`@types/node` unavailable for a Node-typed harness); compiling the production helper separately succeeded. These supplemental checks do not replace canonical repository formatting, lint, Vitest, and production-build validation.

## Private Actions blocker remains active

Private-repository Research Station CI still fails before project code is reached.

Recent exact runtime heads:

- `a338aa676d879b19a83069dc36a88057cd091a8a`: independent document-error channel; run `31290518440`, job `93186733706`, failed with `steps: null`;
- `45c7250bfc40f86b279152011ded94bdafc31902`: fail-closed project-link state and accurate partial-success reporting; run `31290965679`, job `93187920005`, failed with `steps: null`;
- `ccd53a40af6b62d4182c3e2bedecacdbaee39e45`: stale-project async guards plus project-link retry; run `31291028502`, job `93188099034`, failed with `steps: null`.

Documentation-only heads also reproduced the same signature, including runs `31291057324` / job `93188183032` and `31291118700` / job `93188354590`.

No checkout, formatting, lint, test, build, or application step executed on those runs.

Controlled diagnostics remain decisive:

- public `jsp1440/orchid-continuum-frontend` executes equivalent Ubuntu and Windows hosted-runner probes;
- private `jsp1440/orchid-calyx-backend` fails the probes before step 1;
- private `jsp1440/Orchid-Continuum-Brain` fails the probes before step 1.

The failure therefore follows private repositories under the personal account rather than RS-15 code, one repository workflow, Linux, Windows, checkout, language setup, or GitHub-hosted runners generally. Canonical infrastructure incident remains backend issue #481.

## Governance boundary

Do not:

- mark RS-15 review-ready before an exact-head full Research Station gate executes successfully;
- merge or deploy RS-15;
- make a private repository public as a CI workaround;
- enable paid Actions overage, change a payment method, or increase a hard-stop Actions budget without owner decision;
- interpret conversation text as evidence or authorize scientific publication / Knowledge Graph mutation through this work.

## Recovery sequence

1. Restore private-repository hosted Actions execution at the account/repository administrative layer.
2. Run the unchanged latest RS-15 code through the complete Research Station gate.
3. Fix any real formatter/lint/Vitest/build failure before expanding scope.
4. Promote PR #17 only after one exact head is fully green.
5. Only then proceed to RS-16 or another source-archive capability.
