# OCU-SCI-009C — Scientific Stage Exit Gates

## Purpose

Make the inquiry workflow a server-enforced scientific contract rather than a frontend convention.

OCU-SCI-009A enforced stage ordering and revision concurrency. OCU-SCI-009C adds substantive stage-completion rules so a direct API client cannot advance an empty investigation simply by posting `stage_advanced` events.

## Event-to-stage binding

Durable learner events are bound to the inquiry stage where they have scientific meaning:

- `observation_added` → `observe`
- `question_set` → `question`
- `hypothesis_added` → `investigate`
- `evidence_examined` → `investigate`
- `analysis_recorded` → `analyze`
- `interpretation_recorded` → `interpret`
- `conclusion_drafted` → `communicate`
- `uncertainty_recorded` → `communicate`

`stage_advanced` is the only ordinary event that may target the next stage, and it may advance exactly one stage.

The `contribute` transition remains reserved for the explicit submission endpoint.

## Stage exit requirements

Before `stage_advanced` is accepted, the server verifies that the current stage contains the required substantive learner records:

- Observe: at least one observation
- Question: a testable-question record
- Investigate: at least one hypothesis and one examined-evidence record
- Analyze: an analysis record
- Interpret: an interpretation record
- Communicate: a conclusion draft and an uncertainty record

A missing requirement returns `STAGE_EXIT_REQUIREMENTS_UNMET` and commits nothing.

## Submission

Submission now requires the session to be exactly in `communicate`, not merely at or beyond it, and independently rechecks the communicate exit requirements before creating the immutable `session_submitted` event.

This prevents direct API callers from bypassing the notebook's conclusion/uncertainty requirements.

## Changes requested

A `changes_requested` review reopens the session at `communicate`.

For resubmission, the server reads the latest changes-requested review revision and requires a **new post-review communicate cycle**. Both of the following must occur at revisions newer than the reviewed revision:

- `conclusion_drafted`
- `uncertainty_recorded`

Immediate resubmission of the unchanged prior conclusion is rejected with `CHANGES_NOT_ADDRESSED` or `STAGE_EXIT_REQUIREMENTS_UNMET`.

## Error semantics

Expected scientific-workflow violations map to conflict/client responses, not HTTP 500:

- `EVENT_STAGE_MISMATCH`
- `STAGE_EXIT_REQUIREMENTS_UNMET`
- `INVALID_STAGE_TRANSITION`
- `SUBMISSION_ENDPOINT_REQUIRED`
- `SUBMISSION_NOT_READY`
- `CHANGES_NOT_ADDRESSED`

## Unchanged governance boundaries

This build does not:

- apply the University database migration;
- enable durable sessions in production;
- alter the OCU-SCI-007 evidence gate;
- enable Calyx model calls;
- enable Candidate Knowledge writes or promotion;
- enable publication.

The new rules take effect only if the already fail-closed durable-session activation gate is later opened after production verification.
