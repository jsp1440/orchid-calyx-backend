# BUILD-617 — Mechanistic Contradiction Accounting

## Status

R2 is implemented and executable-green on `feature/build-617-mechanistic-contradictions-r2`, rebuilt directly from the corrected BUILD-616 head. Replacement PR #786 supersedes the stale/non-mergeable original BUILD-617 stack.

The validated code head is `ea88483d92cfac2827014e43020a41ffa4dd9e93`. Dedicated BUILD-617 run `31301238604` passed compile, Ruff lint and formatting, BUILD-617 behavioral regressions, BUILD-616 and BUILD-615 prerequisite regressions, authenticated route verification, and repository hygiene. Applicable broad checks also passed: Candidate Handoff, BUILD-616, BUILD-615, Workflow Governance, Brain E2E, Calyx Brain Integration, OC Platform Routes, and OC Parallel Platform.

Executable CI first exposed only mechanical lint/format findings in the reconstructed slice. Those were corrected before behavioral validation was accepted. No failing behavioral or governance assertion remains on the validated code head.

## Purpose

Candidate Knowledge conflict detection is predicate-specific. Scientifically opposite causal claims can therefore both remain active when their predicates differ, for example:

`blue light --promotes--> auxin redistribution`

and

`blue light --inhibits--> auxin redistribution`

BUILD-617 adds a read-only contradiction layer that detects opposite controlled causal polarity across the same mechanistic scope before a BUILD-616 publication plan can be considered ready.

## Scope identity

Mechanistic candidates are compared only when they share the same:

- source canonical key;
- target canonical key;
- explicit taxon scope when present;
- experimental context;
- quantitative context.

This conservative equality rule avoids treating observations from different tissues, developmental stages, environments, treatments, or quantitative regimes as direct contradictions.

## Contradiction rule

Within one exact scope, a contradiction exists when at least one active controlled causal candidate has positive polarity and at least one active controlled causal candidate has negative polarity.

Zero-polarity regulatory relations do not alone form a contradiction.

Each contradiction cluster contains a deterministic contradiction ID, scope identity, participating candidate IDs, positive and negative candidate IDs, relationship names, evidence count, review states, and explicit `publication_blocking=true` / `resolved=false` markers.

The analyzer is read-only. It does not mutate Candidate Knowledge, review state, conflict state, or the canonical Knowledge Graph.

## Publication-plan integration

BUILD-616 publication planning now queries the contradiction analyzer. A participating unresolved contradiction contributes a blocker:

`mechanistic_contradiction:<contradiction_id>`

Therefore even independently approved candidates cannot become ready for the controlled publication gate while opposite-polarity evidence exists in the same exact scientific scope.

This layer does not decide which scientific claim is correct. Resolution remains a separate scientific review/governance action and must preserve both evidence chains and reviewer rationale.

## API

Authenticated read endpoint:

`GET /api/platform/brain/mechanistic-contradictions`

## Governance boundaries

BUILD-617 cannot:

- resolve a contradiction;
- prefer one candidate, paper, author, or result automatically;
- modify scientific review state;
- set `published=true`;
- publish, retract, or mutate canonical graph knowledge;
- broaden or narrow scientific scope silently.

## Validation contract

`tests/test_build_617_mechanistic_contradictions.py` covers:

- positive versus negative polarity in the same scope produces one contradiction cluster;
- different experimental scope does not create a false contradiction;
- an otherwise approved BUILD-616 publication plan is blocked by contradiction membership;
- same-polarity replicate evidence is not classified as contradiction.

The dedicated workflow additionally compiles the BUILD-617 slice, runs Ruff lint and format checks, executes BUILD-617 behavioral tests, runs BUILD-616 and BUILD-615 regressions, verifies the authenticated contradiction route, and performs repository hygiene checks.

## R2 provenance

The original BUILD-617 PR was based on a pre-correction BUILD-616 head and became non-mergeable after BUILD-616 received executable fixes. R2 was rebuilt from the corrected BUILD-616 head instead of force-merging or masking that stale stack. The inherited BUILD-616 canonical endpoint identity fix is therefore preserved before contradiction accounting is added.

## Next work

1. Merge only after BUILD-616 / PR #740 lands and the stack is retargeted/revalidated as needed.
2. Add explicit structured scope fields for taxon, tissue, developmental stage, treatment, dose/range, and environment rather than relying only on context dictionaries.
3. Design governed contradiction-resolution records that preserve both sides and reviewer rationale without deleting evidence.
4. Expose contradiction state to Calyx reasoning responses so contested mechanisms are surfaced rather than silently flattened.
