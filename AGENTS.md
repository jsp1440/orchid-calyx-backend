# Calyx Agent Operating System

These rules apply to every coding-agent session in this repository.

## Mission

Advance the Calyx accelerated completion program to a working, review-governed scientific system. GitHub issues and pull requests are the durable control plane. The repository owner must never be used as a prompt relay, CI monitor, branch coordinator, or copy-and-paste message bus.

## Authoritative work selection

1. Read the linked issue, parent issue #384, current `main`, all open pull requests, issue comments, review comments, and required checks before changing code.
2. Search for an existing branch or pull request for the same acceptance criterion.
3. Exactly one pull request may be authoritative for a given issue. Reuse it whenever technically possible.
4. Never create a duplicate pull request merely because an earlier session stopped. Continue the existing branch or clearly supersede and close the older draft in the same session.
5. Treat closed duplicate PRs as historical only. Do not target or revive them unless explicitly instructed.

## Parallel execution lanes

Keep independent work in separate lanes:

- Lane 1: Brain mission and Reasoning Ledger integration.
- Lane 2: taxonomy and occurrence pipelines.
- Lane 3: licensed images and literature pipelines.
- Lane 4: operator UI and browser/API certification.
- Lane 5: deployment QA, observability, and production-readiness reporting.

Do not modify another lane's files unless a shared contract change is unavoidable. When a shared contract must change, document it in the PR body and notify the affected issues.

## Session completion contract

Every session must end in exactly one of these states:

### A. DELIVERED
- commit and push the work;
- open or update the authoritative pull request;
- run focused tests, compilation, lint on changed files, and `git diff --check`;
- comment on the linked issue with the PR number, commit SHA, tests, and remaining work.

### B. BLOCKED
- make no fabricated progress claims;
- add a `BLOCKED` issue comment naming the exact missing credential, file, service, approval, dependency, or failing contract;
- include the next executable action and who or what can perform it;
- preserve any useful branch or commit and identify it.

### C. NO-OP
- only when the acceptance criterion is already satisfied on current `main` or by an existing authoritative PR;
- comment with the exact evidence and do not create another branch or PR.

A session must never fail silently. A red or timed-out cloud-agent run without a PR or issue comment is an incomplete session and must be restarted by the coordinator.

## Recovery rules

1. On each coordinator run, inspect open accelerated issues for a recent PR, branch, or explicit blocker comment.
2. An issue with no deliverable or blocker after a failed/timed-out session is `UNSTARTED`, not in progress.
3. Restart the highest-priority unstarted lane immediately; do not wait for the owner.
4. The coordinator may maintain up to five independent active coding lanes, but only one active implementation per issue.
5. Prefer several non-overlapping tasks in one coordinator run when tool and session limits permit. Do not serialize independent lanes unnecessarily.
6. When `main` advances, rebase or update active branches before further implementation when safe.

## CI policy

1. Distinguish failures introduced by the PR from failures that reproduce on current `main`.
2. Fix PR-introduced failures.
3. Do not alter unrelated legacy modules solely to make an unrelated PR green.
4. For baseline failures, record exact workflow, job, step, file, and reproduction evidence in the PR.
5. A baseline-failure waiver must be explicit and evidence-based; never label a failure "pre-existing" without checking current `main`.
6. Do not weaken tests, authentication, review gates, publication safeguards, or provenance requirements.

## Scientific and governance boundaries

- No automatic production Knowledge Graph publication.
- Human scientific review remains mandatory.
- No invented evidence, counts, identifiers, provenance, test results, or production status.
- Claims, evidence, inference, contradiction, uncertainty, and missing evidence remain distinct.
- Do not store or expose private chain-of-thought.
- No direct production database credentials in GitHub.
- Bounded, resumable, idempotent operations only for production-facing jobs.

## Hassler taxonomy acceptance

The real acceptance target is `WorldOrchids 26-08 (Aug 2 2026).csv`, not a toy fixture. The supported lifecycle is:

`upload → checksum/release record → schema validation → normalization → comparison → reviewed change report → bounded staging projection → idempotency proof → owner-approved activation → species API verification`

Fixtures are safety tests only. No automatic activation is allowed.

## Owner interaction

Ask the owner only for genuine authority or unavailable private inputs:

- scientific approval or rejection;
- production publication authorization;
- a missing private credential or external file;
- spending approval;
- a product decision that cannot be inferred from the issue.

Do not ask the owner to relay prompts, copy hashes, monitor checks, choose routine next tasks, or restart failed sessions.
