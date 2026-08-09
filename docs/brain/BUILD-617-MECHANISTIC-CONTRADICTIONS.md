# BUILD-617 — Mechanistic Contradiction Accounting

## Status

Implemented on stacked branch `feature/build-617-mechanistic-contradictions`, based on BUILD-616 and BUILD-615. It must not merge before those prerequisites and executable repository CI are restored.

## Purpose

Candidate Knowledge conflict detection is predicate-specific. That means scientifically opposite causal claims such as:

`blue light --promotes--> auxin redistribution`

and

`blue light --inhibits--> auxin redistribution`

can both remain active because their predicates differ. BUILD-617 adds a read-only contradiction layer that detects opposite causal polarity across the same mechanistic scope before a publication plan can be considered ready.

## Scope identity

Mechanistic candidates are compared only when they share the same:

- source canonical key;
- target canonical key;
- explicit taxon scope when present;
- experimental context;
- quantitative context.

This conservative equality rule avoids treating observations from different tissues, developmental stages, environmental ranges, or quantitative regimes as direct contradictions.

## Contradiction rule

Within one exact scope, a contradiction exists when at least one active controlled causal candidate has positive polarity and at least one active controlled causal candidate has negative polarity.

Regulatory zero-polarity relations are not by themselves treated as contradictions.

Each contradiction cluster contains:

- deterministic contradiction ID;
- scope identity;
- all candidate IDs;
- positive and negative candidate IDs;
- relationship names;
- evidence count;
- review states;
- `publication_blocking=true`;
- `resolved=false`.

The analyzer is read-only and does not mutate Candidate Knowledge or the Knowledge Graph.

## Publication-plan integration

BUILD-616 publication plans now query the contradiction analyzer. Any participating contradiction adds a blocker of the form:

`mechanistic_contradiction:<contradiction_id>`

Therefore even independently approved candidates cannot proceed to the controlled publication gate while opposite-polarity evidence exists in the same scientific scope.

This does not decide which claim is correct. Resolution remains a scientific review/governance action.

## API

Authenticated read endpoint:

`GET /api/platform/brain/mechanistic-contradictions`

## Governance

BUILD-617 cannot:

- resolve a contradiction;
- prefer one paper, candidate, author, or result automatically;
- modify scientific review state;
- publish or retract graph knowledge;
- broaden or narrow experimental scope silently.

## Validation

`tests/test_build_617_mechanistic_contradictions.py` covers:

- positive versus negative polarity in the same scope produces one contradiction cluster;
- different experimental tissue scope does not create a false contradiction;
- an otherwise approved BUILD-616 publication plan is blocked by contradiction membership;
- same-polarity replicate evidence is not classified as a contradiction.

Repository CI remains blocked by hosted-runner issue #481, so BUILD-617 remains a stacked, unmerged implementation until executable validation returns.

## Next work

1. Add explicit structured scope fields for taxon, tissue, developmental stage, treatment, dose/range, and environment instead of relying only on free-form context dictionaries.
2. Add governed contradiction-resolution records that preserve both sides and reviewer rationale without deleting evidence.
3. Feed contradiction state into Calyx reasoning responses so users can see when a causal explanation is scientifically contested.
