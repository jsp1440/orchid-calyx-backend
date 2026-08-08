# BUILD-BRAIN-114O — Reviewed owner-bound Git mutation authorization

## Objective

Create a non-mutating authorization boundary between reviewed BUILD-BRAIN-114M proposal evidence and any future Git/GitHub proposal executor.

## Required evidence

114O accepts an exact 114M manifest only after BUILD-BRAIN-114N has stored both required review classes in the authoritative `ProposalAuthorizationRegistry` for that same manifest digest. It does not trust caller-supplied review objects. `proposal_review_status()` must report `PROPOSAL_REVIEW_EVIDENCE_COMPLETE`, then the gate retrieves the exact `operational` and `security` records from the registry, verifies them against the manifest, requires both approvals, and requires distinct reviewers.

This registry lookup closes a confused-deputy gap in the earlier precursor design: constructing a standalone `ProposalAuthorizationRecord` object is not sufficient evidence. The record must already be the authoritative immutable registry decision for the exact manifest and review class.

## Request binding

A successful authorization request is deterministically bound to the exact 114M manifest digest, repository and 40-character base commit, `autonomy/proposal/*` branch, every changed-file postimage SHA-256, every validation receipt digest, both authoritative 114N authorization digests, the explicit allowlisted action set, and an expiry no more than 30 minutes in the future.

Allowed future action names are limited to `create_branch`, `create_commit`, `push_branch`, and `open_pull_request`.

## Owner grant

An externally configured owner principal and HMAC-SHA-256 secret sign an exact request digest. Wrong request, wrong owner, denial, invalid signature, future-issued grant, mismatched expiry, or expired grant fails closed.

## Permanent boundaries

114O performs no Git or GitHub mutation. It grants no merge or auto-merge, deployment, publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation authority. It contains no Git, subprocess, HTTP, deployment, publication, or production-mutation executor.

Actual branch/commit/push/PR creation is a separate governance milestone and is not implemented here.

## Validation

Dedicated CI compiles the 114O/114N surfaces, runs Ruff, executes focused registry/review/owner-expiry regressions, statically asserts the non-mutation boundary, and runs diff hygiene.

Canonical CI issue #481 currently records repository jobs terminating before checkout with `steps=null`; such attempts are infrastructure evidence only and provide no code verdict. Keep this slice draft until exact-head CI executes real steps and passes.
