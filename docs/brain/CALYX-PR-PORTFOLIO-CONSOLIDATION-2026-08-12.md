# CALYX PR Portfolio Consolidation — 2026-08-12

## Decision

Backend pull requests are treated as an active integration queue, not an archive. Historical implementation remains recoverable through closed PRs and Git history.

## Active integration policy

- Keep the open backend PR set at or below 10.
- Prefer current-main integration branches.
- Close stale/diverged stacked branches without merge after recording the successor or reconstruction path.
- Do not interpret GitHub Actions jobs with `steps: null` / no assigned runner as code validation.
- Do not blind-rerun zero-step jobs; executable jobs with non-empty step lists are the recovery signal.
- Do not merge, deploy, activate taxonomy, apply production migrations, publish science, mutate the production Knowledge Graph, spend funds, or delete branches without the applicable governance authority.

## Consolidation performed

The prior large draft queue was reduced to a small active set. On this pass, stale/diverged PRs #735 (governed glossary intake), #737 (unified owner flow), #819 (combined 101→140 validation head), and #734 (guarded Hassler upload client) were closed without merge. Their histories remain preserved as reconstruction evidence.

Current-main successors/authorities include:

- #900 — durable mission queue / validator-driven worker;
- #897 — runtime vs migration database-target equivalence;
- #896 — canonical Lexicon direct-entry contract;
- #894 — Matrix session optimistic concurrency;
- #893 — integrated grounded Speak/Matrix/provider-readiness workspace;
- #878 — protected live Speak acceptance harness.

## Reconstruction rule

A closed historical PR may be reused only by replaying the still-required capability onto current `main` (or an explicitly designated current integration branch), preserving tests, provenance, and governance constraints. Do not revive a stale branch merely to reduce implementation effort.

## Current infrastructure boundary

Private GitHub-hosted Actions remain unable to provide trusted exact-head validation while jobs terminate before step creation. This is an infrastructure blocker, not executable evidence of test failure or success. The active PRs remain draft/unmerged until executable validation is restored or an equivalently trusted validation path is available.
