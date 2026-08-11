# CALYX-SPEAK Live Acceptance — Current-Main Refresh

Date: 2026-08-11

## Purpose

Reconstruct the protected production-only Speak with CALYX acceptance harness directly on current canonical `main` after the prior validation branch diverged.

## Scope

- Adds the authenticated live acceptance script and protected GitHub Actions workflow.
- Uses the frontend-equivalent HttpOnly owner session cookie flow.
- Verifies deployed CALYX-SPEAK release identity, creates a server-owned conversation, executes a five-turn CALYX Vision requirements dialogue, restores the transcript, and records provider / retrieval / Brain mission metadata.
- Fails if substantive turns use the deterministic-governed fallback.

## Governance

This change adds validation tooling only. It does not itself dispatch the production workflow and does not authorize or perform production database migration, deployment, scientific publication, Candidate Knowledge promotion, taxonomy activation, production relink, or Knowledge Graph mutation.

The production acceptance run remains a separate protected-environment action after required production migration/deployment authorization.

## Canonical relationship

This refresh supersedes stale validation PR #867 once merged. The previous branch was 34 commits behind `main`; this successor is rebuilt from current `main` and contains only the validation harness and this Brain record.
