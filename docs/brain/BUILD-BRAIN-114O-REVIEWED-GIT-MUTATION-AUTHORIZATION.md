# BUILD-BRAIN-114O — Reviewed Git mutation authorization boundary

## Objective

Place a second, explicit authorization layer between the evidence-bound proposal/review chain and any future Git/GitHub mutation executor. 114O does not mutate Git or GitHub. It determines whether an exact proposal is eligible to receive a short-lived owner grant for a tightly bounded set of future Git actions.

## Dependency chain

114O is built on the current 114N proposal-review branch so that the review record type is part of the same tested merge context. The intended chain is:

`114M evidence-bound proposal → 114N role-qualified proposal review → 114O owner-bound mutation authorization → future mutation executor`

The final arrow does not exist yet.

## Required reviews

Before an authorization request can be created, the exact 114M manifest must have both:

- one approved `operational` 114N review; and
- one approved `security` 114N review.

The two review records must verify against the exact manifest digest and must be issued by distinct reviewers. 114N itself already prevents a reviewer from being the requester or derived patch producer. 114O additionally prevents one reviewer from satisfying both required review classes.

The immutable 114N `authorization_digest` values are embedded in the 114O request digest, so changing either review invalidates the owner authorization request.

## Owner-bound grant

An authorization request binds:

- exact 114M manifest digest;
- repository;
- exact base Git commit;
- proposed `autonomy/proposal/*` branch;
- every changed-file postimage SHA-256;
- every successful validation receipt digest;
- both required 114N review authorization digests;
- explicit allowlisted actions;
- an expiry no more than 30 minutes in the future.

The owner grant is bound to that exact request digest and protected by an externally supplied HMAC-SHA-256 secret. Wrong owner identity, denial, expiry, request drift, or signature mismatch fails closed.

## Allowed future action scope

Only these action names can appear in a valid request:

- `create_branch`
- `create_commit`
- `push_branch`
- `open_pull_request`

This module implements none of them. It has no subprocess, Git, HTTP, GitHub, deployment, publication, database-mutation, or Knowledge Graph mutation executor.

## Permanent exclusions

A valid 114O request explicitly keeps the following false:

- merge authority;
- deployment authority;
- scientific publication authority;
- taxonomy activation authority;
- production database mutation authority;
- production Knowledge Graph mutation authority.

Auto-merge is likewise outside the allowlist.

## Validation

The dedicated read-only 114O workflow compiles and lints the 114N/114O authorization surfaces, runs the existing 114N tests plus focused 114O regressions, statically checks non-mutation boundaries, and performs diff hygiene.

As of this slice, GitHub issue #685 records an external Actions incident in which connector/agent-authored PR heads terminate before checkout with `steps=null`. Therefore no exact-head CI success is claimed until GitHub actually executes the workflow steps. The branch remains draft and unmerged while that infrastructure incident is unresolved.
