# Orchid Continuous Execution Rule

Status reports are execution checkpoints, not endpoints.

This rule applies to every autonomous or agent-assisted implementation lane used by Orchid Continuum, including Claude, Codex, ChatGPT, and future providers.

## Required terminal transition for every work item

Completing implementation or producing a status report is never, by itself, a stopping condition. At the end of every bounded work item the agent or supervisor MUST:

1. **VERIFY** — verify the implementation and its tests against GitHub source of truth, including exact-head workflow evidence when a PR exists.
2. **REPORT** — emit a concise checkpoint containing what changed, verification evidence, errors or failures, the likely cause when known, and the recommended correction.
3. **REPAIR** — convert every safe, correctable failure or incomplete acceptance criterion into an explicit next action and execute the highest-priority one without waiting for an owner response.
4. **CONTINUE** — repeat repair → test → verify until the current item reaches its permitted completion state.
5. **SELECT NEXT TASK** — when the current item has no remaining executable action, immediately re-enter the canonical DeepOrchestrate/portfolio scheduler. The scheduler selects the highest-priority eligible, unblocked task, atomically leases it, and dispatches the next bounded execution lane.
6. Repeat this cycle continuously.

Canonical loop:

`VERIFY → REPORT → REPAIR → CONTINUE → SELECT NEXT TASK`

## Owner gates

Autonomous continuation stops only when the next required action crosses an owner gate or cannot be performed safely. Owner gates include:

- credentials, permissions, or secrets that are unavailable;
- irreversible or destructive operations;
- production deployment or promotion to the protected production branch;
- destructive database operations or irreversible migrations;
- production data mutation outside an already-authorized reversible path;
- exposure of sensitive locality or other protected scientific data;
- material new spending or activation of a new paid service;
- unresolved architectural conflict where competing changes cannot safely be reconciled automatically;
- any action explicitly reserved to the owner by repository governance.

An owner-gated task MUST be durably marked `oc-owner-gate` (or the repository-equivalent protected state), MUST NOT consume an execution lane, and MUST NOT prevent unrelated eligible work from continuing.

## Failure semantics

A failed implementation or validation is not a generic stop condition.

- A correctable code or test failure transitions to bounded repair (`oc-repair`) and is retried according to repair/backoff policy.
- A provider/runtime failure follows the runtime backoff circuit and is retried only when the provider circuit permits it.
- A repeated failure that reaches bounded-repair limits is parked in repair backoff rather than thrashed.
- A genuine owner gate is surfaced to the owner while the scheduler continues unrelated work.

## Completion reporting contract

Every checkpoint SHOULD expose, at minimum:

- work item / PR / exact head;
- implementation delta;
- verification state;
- errors or failed checks;
- likely cause, when evidenced;
- correction performed or queued;
- next action selected;
- continuation decision: `REPAIR`, `CONTINUE`, `SELECT_NEXT_TASK`, or `OWNER_GATE`.

The report is evidence for the next transition. It does not terminate execution.

## Persistent execution

Conversation sessions are not the persistence mechanism. GitHub Actions plus the durable issue/PR state machine are. The completion lane emits a terminal event; the continuation supervisor immediately wakes the canonical continuous-completion scheduler. The existing periodic scheduler remains a recovery heartbeat so a missed event cannot permanently stop the system.
