# BUILD-BRAIN-114 — Repository Hygiene and Authoritative Branch Cleanup

## Status

Completed on 2026-08-07.

## Purpose

Reduce ambiguity in the Orchid Calyx backend by retiring superseded pull requests and identifying the authoritative Brain execution chain.

## Authoritative Brain execution chain

The operational Brain execution work is represented by the validated and merged BUILD-BRAIN-108 through BUILD-BRAIN-113A sequence:

- governed executor boundary;
- receipt-backed lease completion;
- deterministic dependency scheduling;
- persisted scheduler and Mission Control integration;
- governed assignment creation;
- protected deterministic dry-run execution loop.

BUILD-BRAIN-113A merged as commit `3621454df9d15f9a12793290f32b495adbd06681`.

## Retired pull requests

The following non-authoritative branches were closed:

- PR #405 — superseded CI repair;
- PR #411 — superseded CI repair;
- PR #412 — superseded CI repair;
- PR #436 — superseded by PR #509;
- PR #425 — canonical Brain integration umbrella, explicitly not a direct merge candidate;
- PR #488 — stale stacked Brain Slice 2;
- PR #489 — stale stacked Brain Slice 3.

Each retained Git history entry remains available for provenance.

## Active work classification

Active feature branches must be treated as independent bounded programs and must be rebased or rebuilt on current `main` before merge consideration. Current examples include canonical Brain registry/governance slices, Azure taxonomy pilot guardrails, Atlas, Literature/Matrix/AI.Vision, and Calyx Core mission/operator pipelines.

## Governance rules

1. Umbrella branches are never direct merge candidates.
2. A superseding PR must identify the replaced PR explicitly.
3. Superseded PRs should be closed once the replacement exists and provenance is recorded.
4. Automation-authored `action_required` workflow states are not test evidence.
5. Only an unchanged head with completed successful checks may merge.
6. Deployment, publication, taxonomy activation, credential access, and production Knowledge Graph mutation remain separate governance boundaries.

## Current next gate

PR #509 contains the latest shared CI repair and supersedes PR #436. Its automation-authored workflow attempts were blocked at `action_required`; it requires an owner-authored synchronization commit and successful validation before merge.
