# ACS-CLAUDE-ADAPTER-001: Claude consumer adapter runbook

- **Assignment:** https://github.com/jsp1440/orchid-calyx-backend/issues/1823#issuecomment-6158142354
- **Code:** `coordination/claude_adapter.py`
- **Tests:** `tests/coordination/test_acs_claude_adapter.py`
- **Base:** ACS-001 coordinator (#1833, `feat/agent-coordination-1823`). It reuses that coordinator's store, event schema, signed ingress, GitHub bridge and report projection.

## What the adapter does

1. **Discover**
   - Co-located: `StoreTransport` reads `acs_tasks` for agent `claude`.
   - Remote: `ReportDiscovery` reads the coordinator's own hub reports. Only reporter-id comments with the exact `<!-- OC-ACS:... -->` canonical JSON projection count.
2. **Refuse without executing** anything whose action is not `engineering` or whose state is `owner_gate`, even after an owner acknowledgement. The adapter emits a `BLOCKED` record with `executions: 0`.
3. **Claim** through the ACS protocol. That is in-process with the `agent:claude` principal, or HMAC-signed `POST /events` with an agent-only key. The coordinator returns a fenced lease token. The lease is written to the adapter's persistent SQLite state before any work starts.
4. **Receipt.** A `[OC-COORD-INPUT] RECEIPT` is posted to the canonical PR.
5. **Screen the objective text.** It is untrusted. Shell blocks, pipe-to-shell, destructive commands, instruction overrides, credential requests and gated-action requests reject the task with `UNTRUSTED_INSTRUCTIONS_REJECTED` and zero execution. The executor gets only the objective URL and a digest of the text, never the text as instructions.
6. **Execute and heartbeat.** The adapter steps the executor and sends a heartbeat after every step.
   - Lease lost to another worker → `fenced`; the result is discarded.
   - Attempt deadline reached → `timed_out`; the coordinator retries, and dead-letters after 3 attempts.
   - Kill switch engaged → the job is cancelled and the task responds `blocked`.
7. **Respond** `delivered` (all offline checks passed) or `blocked`, with the canonical PR as reference. A `[OC-COORD-INPUT] RESULT` carries the outcome, check results and the artifact's sha256.

### Durable state
- Lease, dedup keys, outbox, dead letters and audit log live in one SQLite file. `:memory:` is refused.
- After a restart, a still-valid lease is resumed with its stored token, and an expired one is abandoned.
- Dedup records decisive outcomes only (claimed or refused). A failed claim stays retryable, with backoff of 10 s, 20 s, ... capped at 300 s.
- Exceeding `max_local_retries` dead-letters the task locally. Coordinator state is never faked.

### Result outbox
- Every message has a stable marker, and the PR is re-read before every POST.
- An identical marked comment from the reporter identity reconciles an ambiguous earlier POST instead of posting twice.
- Undeliverable messages are dead-lettered after 3 attempts.

### No loops
- Coordinator receipts (`[OC-COORD-AUTO]`), self-declared "Claude" text and this adapter's own comments never become tasks.

## What is disabled

| Control | Default | How it changes |
|---|---|---|
| Executor | `MockClaudeExecutor`: offline, deterministic, no model call | A `ClaudeRunner` implementation (none is shipped) |
| Live execution | `ExecutionPolicy.live_enabled=False`. `ClaudeRunner` refuses without that flag, an identity-scoped credential reference and an owner-approval reference, and refuses to start even then (`NO_SUPPORTED_LIVE_RUNNER_CONFIGURED`). | Owner decision plus a reviewed runner implementation |
| Concurrency | exactly 1 (other values are refused) | Reviewed code change only |
| Budget | 10 executions / 24 h | `ExecutionPolicy.max_executions_per_day` |
| Actions | `engineering` only; privileged actions are refused at construction | Not configurable |
| Kill switch | A file path; its existence stops claims and cancels work | Operator |
| Result transport | CLI has none (posts fail closed into the outbox) | PR-scoped reporter token, not provisioned |

CLI: `python -m coordination.claude_adapter once|status|readiness --state PATH [--coordinator-sqlite PATH]`. `--live` raises `LiveExecutionDisabled`.

## How Claude receives assignments without a human relay

**Observed and working:** the Claude Code cloud session that wrote this adapter (`session_01JLryb45QVLpFeUZfBnkn5c`) is subscribed to this PR's activity (`subscribe_pr_activity` on #1836, confirmed 2026-10-14). New comments, reviews, CI results and commits on #1836 are delivered into that session as events. Nobody needs to copy text into chat.

ChatGPT should therefore put Claude assignments and replies as a comment on #1836, the Claude adapter's canonical PR, and may mirror them to hub #1823.

Limits:
- Standalone hub issue comments are not delivered. Only PR events are.
- The subscription belongs to that one session and ends when #1836 is merged or closed, or when the session is stopped.
- The comment author (`jsp1440`, shared by every agent) does not authenticate the sender. The session treats event text as information, not instructions. Owner gates (merge, deploy, production, credentials, spending) still need the owner.

**Durable fallback (supported, not activated):** a Claude Code Routine. This is a scheduled trigger that starts a fresh cloud session on a cron. Each run would execute `python -m coordination.claude_adapter once` against the deployed coordinator with an agent-only key, or read #1836 and #1823. Each run consumes the owner's Claude plan, so creating the Routine is an owner decision. It was not created.

**Machine path once ACS is deployed:**
- An owner-issued, agent-only HMAC key for `claude` in the runner environment (`ACS_CLAUDE_INGRESS_URL`, `ACS_CLAUDE_KEY_ID`, `ACS_CLAUDE_KEY_SECRET`). `SignedIngressTransport.from_env` returns `None` until all three exist.
- Hub reporter ids for `ReportDiscovery`.
- A PR-scoped reporter token for `ResultPublisher`.

None of these is provisioned. No credential was created, requested or reused.

**How results wake ChatGPT:** receipts and results are PR comments on #1836. ChatGPT's event lane wakes on new PR comments (`docs/coordination/GITHUB-EVENT-LANE.md`), so a posted result is a supported wake-up for it.

## Live readiness

`live_readiness(...)` returns `ready: false` until all of these are observed:
- an agent-only signed key;
- a supported live runner;
- a distinct agent identity;
- a real Claude adapter result URL on GitHub.

`test_live_claim_requires_an_observed_claude_result` is skipped unless `ACS_CLAUDE_LIVE_RESULT_URL` (and the related variables) point at real evidence. No one should claim unattended Claude operation before that test passes against a real result.

## Validation (offline)

```
python -m ruff check coordination tests/coordination
python -m ruff format --check coordination tests/coordination
python -m compileall -q coordination tests/coordination
python -B -m unittest discover -s tests/coordination -v
```

The scenarios covered by tests:
- signed-ingress end to end through fake GitHub;
- duplicate and replayed events;
- stale-worker fencing;
- restart with a valid lease and with an expired lease;
- timeout → retry → dead letter;
- transport backoff → dead letter;
- kill switch;
- ambiguous POST reconciliation and undeliverable results;
- forged and self-declared assignments, and adapter/coordinator echo loops;
- prompt injection, plus benign text;
- an owner-gated task even after approval;
- live-runner and policy bounds, the budget limit, the CLI, and live readiness.
