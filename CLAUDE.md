# Orchid Continuum Calyx Backend — Claude Code Adapter

This repository is the canonical Calyx backend execution surface for Orchid Continuum.

Claude Code is an executor, not the source of truth for project state.

## Authority

- Read `AGENTS.md` first. It is the repository's primary coding-agent operating system.
- Orchid Continuum Brain owns architecture, governance, mission intent, scientific-integrity rules, and durable completion records.
- GitHub owns code, issues, branches, pull requests, CI, reviews, and merge state.
- When a mission references Brain records, inspect those records before implementation.

## Startup sequence

Before editing:
1. Read the linked mission/issue and `AGENTS.md` completely.
2. Inspect current `main`, parent/related issues, open pull requests, review comments, and required checks.
3. Search for an existing authoritative branch/PR for the same acceptance criterion.
4. Identify relevant Brain architecture/governance records.
5. Classify the mission as `NEW`, `CONTINUE`, `CONVERGE`, `SUPERSEDE`, or `ALREADY_DONE`.
6. Reuse or converge existing work instead of creating duplicate implementation lineages.

## Implementation posture

- Maintain the lane separation defined in `AGENTS.md`.
- Preserve scientific provenance, evidence-state distinctions, uncertainty, contradictions, and human-review boundaries.
- Never fabricate production state, counts, identifiers, test results, scientific evidence, or service health.
- Prefer bounded, resumable, idempotent behavior for production-facing jobs.
- Do not weaken authentication, tests, review gates, publication safeguards, or provenance requirements.
- Add focused tests for changed behavior.

## Validation

Follow the repository's existing test and CI conventions. Start with the smallest focused pytest selection that exercises the changed behavior, then broaden to the appropriate repository suite and required GitHub Actions checks.

Also perform changed-file compilation/lint checks where applicable and `git diff --check`, as required by `AGENTS.md`.

Distinguish PR-introduced failures from failures reproducible on current `main`. Never claim a pass without execution evidence.

## Completion states

End each mission in exactly one of the repository-defined states:
- `DELIVERED`: commit/push, authoritative draft PR updated/opened, validation evidence recorded, linked issue updated;
- `BLOCKED`: exact blocker and next executable action recorded, useful branch/commit preserved;
- `NO-OP`: acceptance criteria already satisfied with exact evidence and no duplicate branch/PR.

Continue routine implementation, testing, and repair autonomously. Stop after three unsuccessful attempts on the same deterministic failure class and escalate rather than consuming additional model budget.

## Owner-governed boundaries

Do not merge/auto-merge, deploy/activate production changes, mutate production DB/KG, activate taxonomy, publish scientific knowledge, expose/create/rotate privileged credentials, spend funds, force-push, rewrite history destructively, or delete branches/repos without required owner authorization.

Do not use the repository owner as a prompt relay, CI monitor, branch coordinator, or copy/paste message bus.
