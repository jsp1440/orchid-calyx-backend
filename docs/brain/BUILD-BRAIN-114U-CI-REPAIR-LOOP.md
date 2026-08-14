# BUILD-BRAIN-114U — Governed proposal CI repair loop

**Date:** 2026-08-13  
**Status:** implementation candidate; production persistence activation and live CI/GitHub registration are not performed.

## Purpose

Close the post-draft-PR engineering loop without widening CALYX authority:

`validated proposal mutation receipt → exact draft PR/head CI observation → wait / repair assignment / owner-merge-ready → authoritative correction evidence → exact-head revalidation`

The coordinator does not call GitHub, edit code, push branches, merge pull requests, deploy, or mutate scientific/production data. Failed CI produces only a deterministic corrective-engineering assignment. That assignment explicitly requires the existing authoritative coding executor, fresh validation receipts, and fresh owner authorization before any later Git mutation.

## Trust bindings

A CI observation is accepted only when it matches the durable mutation receipt's repository, draft PR number, and exact commit SHA. Moved/stale heads, mismatched PRs/repos, incomplete mutation receipts, or missing draft-PR evidence fail closed.

The repair key binds:
- source plan digest;
- source mutation receipt digest;
- repository and proposal branch;
- PR number;
- failed exact head SHA;
- exact failed check IDs/names/conclusions;
- observation digest.

Repeated evaluation of identical failure evidence is idempotent. Changed evidence for the same repair/event kind conflicts rather than overwriting durable history.

## CI state behavior

- pending required checks → `waiting`, no repair assignment;
- all checks success/skipped → `ready_for_owner_merge`, with no merge performed;
- failure/cancelled check → `repair_required` plus deterministic governed corrective assignment;
- stale/moved head or identity mismatch → `blocked`.

Revalidation evidence requires an advanced head SHA and a SHA-256 digest of the authoritative corrective receipt. This module records that proof but does not manufacture or execute the correction itself.

## Durability

`calyx_git_proposal_ci_repair_events` is an append-only evidence table with unique `(repair_key, event_kind)` and event digest constraints. The migration is additive and code-only in this candidate. Production migration application is separately governed.

## Permanent non-authority

This slice does **not** authorize or perform:
- merge or auto-merge;
- deployment;
- production database or Knowledge Graph mutation;
- scientific publication or Candidate Knowledge promotion;
- taxonomy activation;
- credentials/secrets registration or disclosure;
- force-push, branch deletion, or spending.

## Validation target

The focused suite covers green/no-mutation behavior, pending checks, deterministic failure assignments, durable replay idempotency, stale-head blocking, PR/repository mismatch blocking, incomplete proposal receipts, advanced-head revalidation, authoritative receipt-digest requirements, and immutable evidence conflicts. Adjacent 114U mutation-executor and GitHub-adapter regressions run in the same hosted workflow.
