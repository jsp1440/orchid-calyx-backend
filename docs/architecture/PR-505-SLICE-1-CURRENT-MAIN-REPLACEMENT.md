# PR #505 — Slice 1 Current-Main Replacement

## Decision

Stale draft PR #487 was closed without merge and replaced by draft PR #505.

## Evidence

At replacement time, `main` had advanced 91 commits beyond the stale Slice 1 branch. The stale branch contained 19 commits and ten additive files, but was reported non-mergeable. The comparison showed that the canonical Brain files did not already exist on current `main`.

## Method

A new branch, `stabilize/brain-slice-1-current-main`, was created directly from current `main`. The exact ten-file Slice 1 surface was transferred without force-pushing, rebasing stale history, or changing the validated application behavior:

- focused Canonical Brain workflow
- package exports
- strict data contracts
- deterministic registry and search
- read-only API
- atomic capture handoff
- canonical architecture fixture
- two focused test modules
- BUILD-BRAIN-100 architecture record

## Carried validation

The identical Python surface previously produced:

- compile: passed
- focused pytest: 7 passed

PR #505 exists to obtain authoritative GitHub Ruff and pytest evidence against current `main`.

## Workflow result at creation

Fresh PR creation immediately produced active BUILD-088E and Canonical Brain Validation runs. The prior `action_required` condition was therefore specific to the stale branch/workflow history rather than a continuing repository-wide policy block.

## Safety

PR #505 remains draft. PR #487 was closed unmerged. No force-push, merge, deployment, publication, production database migration, autonomous write activation, or production Knowledge Graph mutation occurred.
