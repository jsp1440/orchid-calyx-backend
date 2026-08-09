# RS-15 Validation Update — 2026-08-08 19:28 PT

## Scope

This record supplements `RS-12-15-CALYX-SOURCE-WORKFLOW-HANDOFF.md` and captures the latest exact RS-15 runtime hardening and private-repository CI state.

## Current Research Station state

- PR: `jsp1440/orchid-research-station#17` — RS-15 bounded Calyx Source Archive pagination.
- Base: `feature/research-calyx-source-archive-14`.
- PR remains draft, mergeable, unmerged, and non-production.
- Runtime head after latest robustness correction: `a338aa676d879b19a83069dc36a88057cd091a8a`.
- Documentation head after recording the correction: `b16cad8e3774a15225812a212cb0dff867687b67`.

## Runtime correction completed

A component-level review found that RS-15 had two independent asynchronous loads—project document links and paginated conversations—sharing one `error` state. Conversation pagination clears its error state at the start of each page request, so a document-link loading failure could be hidden even though document-link state controls whether a persisted source is displayed as already saved.

The runtime head `a338aa676d879b19a83069dc36a88057cd091a8a` corrects this by:

- adding an independent `documentError` state for project document-link loading;
- clearing only that error when a new document-link load begins;
- preserving conversation/action errors independently;
- explicitly rendering a project-document-link failure message;
- clearing the document error after a successful post-save document refresh.

This does not change source identity, source-save authority, conversation evidence status, publication authority, or Knowledge Graph mutation authority. It is a UI reliability correction only.

## Supplemental validation completed

Before the latest component correction, the actual RS-15 `calyxSourceArchive.ts` helper was compiled successfully with `tsc 5.8.3 --strict` against its imported conversation-type contract. Its emitted JavaScript passed 263,304 boundary/property cases plus a source-archive filtering smoke case. Earlier property validation also passed 42,220 cases after misaligned-offset normalization was added.

The current component correction was statically reviewed against the exact branch file and preserves existing API signatures and provenance rules. Canonical repository formatting/lint/Vitest/production-build validation is still required before review-ready promotion.

## Private Actions blocker remains active

At approximately 19:28 PT, the unchanged prior RS-15 CI run was explicitly rerun. GitHub accepted the rerun, but job `93186541517` again completed before step materialization with `steps: null`.

The new runtime correction automatically triggered CI run `31290518440`; job `93186733706` also completed `failure` with `steps: null`. No checkout, formatting, lint, test, build, or application step executed.

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
2. Run the unchanged current RS-15 head through the complete Research Station gate.
3. Fix any real formatter/lint/Vitest/build failure before expanding scope.
4. Promote PR #17 only after one exact head is fully green.
5. Only then proceed to RS-16 or another source-archive capability.
