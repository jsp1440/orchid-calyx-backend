# ACS Claude Code CLI runner (stacked on ACS-STAGING-PREFLIGHT-002)

- **Code:** `coordination/claude_cli_runner.py` (`ClaudeCodeCliRunner`, a `ClaudeRunner` subclass)
- **Tests:** `tests/coordination/test_acs_claude_cli_runner.py`, which uses a stand-in `claude` executable and makes no model call
- **Hub:** https://github.com/jsp1440/orchid-calyx-backend/issues/1823

## Why it exists

The adapter (#1836) ships `MockClaudeExecutor` and a `ClaudeRunner` interface. That interface refuses with `NO_SUPPORTED_LIVE_RUNNER_CONFIGURED`, because there was no real runner. This module is that runner. It drives the Claude Code CLI headlessly (`claude --print --output-format json`) inside the adapter's existing loop. The adapter's claim, lease, heartbeat, fencing, deadline, kill switch, budget, outbox and coordinator response logic are unchanged.

## Gates (all must pass before a process starts)

| Gate | Refusal code |
|---|---|
| `ExecutionPolicy.live_enabled` | `LIVE_EXECUTION_DISABLED_BY_POLICY` (base class) |
| Credential reference plus an owner-approval GitHub reference | `IDENTITY_SCOPED_CREDENTIAL_AND_OWNER_APPROVAL_REQUIRED` (base class) |
| The credential reference names an `ACS_CLAUDE_*` variable. `ANTHROPIC_API_KEY`, `GH_TOKEN` and similar are rejected. | `CREDENTIAL_REF_MUST_NAME_AN_ACS_CLAUDE_VARIABLE` |
| That variable is present | `CREDENTIAL_NOT_PRESENT` |
| `--max-turns` is between 1 and 50 | `MAX_TURNS_OUT_OF_BOUNDS` |
| The tools are a subset of Read, Glob, Grep, Edit and Write | `TOOLS_OUTSIDE_SAFE_SET` |
| `claude` is installed | `CLAUDE_CLI_NOT_INSTALLED` |
| The run names an independently enforced filesystem boundary (`VERIFIED_CONFINEMENTS`, **empty**) | `WORKSPACE_CONFINEMENT_UNVERIFIED` |
| The capabilities are within the policy and the objective is a GitHub reference | `CAPABILITY_NOT_ALLOWED` / `OBJECTIVE_IS_NOT_A_REFERENCE` |
| Attempt directories are never reused | `ATTEMPT_DIRECTORY_EXISTS` |

## Isolation

> **Workspace confinement is unverified, so live runs are refused.** The working directory, the post-run artifact scan, the private `HOME` and `--allowedTools` are not a filesystem sandbox. Absolute paths and `../` traversal can reach anything the host user can, and writes outside the workspace never appear in the artifact scan. `ConfinementGate.test_writes_outside_the_workspace_leave_the_sentinel_unchanged` shows the escape: it is an expected failure today. Live use needs three things, in order:
> 1. an OS or container boundary that mounts only the task workspace read-write, with no host secrets and no network except the provider;
> 2. that sentinel test passing under the boundary;
> 3. the boundary's name added to `VERIFIED_CONFINEMENTS`.
>
> This was raised in the review on #1841.

- **Working directory.** Each run happens in a private directory, `acs/claude/<task>/attempt-N/workspace`.
- **Logs.** The runner's logs and a private `HOME` live in a separate `runner/` directory, outside what Claude can write.
- **Environment.** The child environment is scrubbed down to PATH, locale and TZ, plus the single mapped credential (`CLAUDE_CODE_OAUTH_TOKEN` or `ANTHROPIC_API_KEY`). The owner's tokens in the parent environment are never inherited.
- **Tools.** Bash, WebFetch, WebSearch, Task and NotebookEdit are always passed as disallowed.
- **Objective text.** The prompt carries the objective reference and the digest of the screened text. The text itself is never inlined, which matches the mock executor contract.
- **Cancellation.** `cancel` sends SIGTERM to the whole process group, then SIGKILL. The adapter calls it on deadline, fencing and kill switch.

## Result verification (offline; the model's own claim is not enough)

`delivered` requires every check to pass:
- clean exit;
- the CLI reported `success`;
- turns within `--max-turns`;
- `RESULT.md` written as a regular file;
- no symlinks or files outside the workspace;
- size and file-count bounds;
- the credential value appears in no output or log;
- no secret-looking assignments in deliverables;
- the objective is a reference.

Otherwise the adapter responds `blocked` (`OFFLINE_CHECKS_FAILED`).

## Demonstrated offline (no model, no network)

The full loop runs through the real coordinator store and bridge:

> owner assignment on the hub → coordinator accepts and routes to `claude` → adapter claims a fenced lease → CLI runner executes → offline checks → `[OC-COORD-INPUT] RESULT` on the canonical PR → coordinator records `delivered` → the next task proceeds → a re-run executes nothing.

Failure modes are each tested: crash, missing result, symlink escape, credential leak, oversize output, turn overrun and a hung process that gets cancelled.

## Not demonstrated, and still owner decisions

Unattended Claude execution is **not** claimed. `live_readiness` still reports `ready: false` until each of the following exists:

1. **A Claude credential for the agent identity**, `ACS_CLAUDE_OAUTH_TOKEN` or an API key. It must belong to an identity that is not the owner's personal login. It consumes the owner's Claude plan or API spend. Owner decision.
2. **An approval reference**: a GitHub issue or PR comment authorising live runs and their budget. Owner decision.
3. **A host that runs the adapter loop with this runner.** Options:
   - a Render worker, which is a new paid service and needs deployment approval;
   - a Claude Code Routine, but Routines are off for the organisation, and enabling them is an admin setting.
4. **The ACS coordinator deployed, plus an agent-only HMAC key and a PR-scoped reporter token**, as listed in `CLAUDE-ADAPTER.md`.
5. **One observed real result URL.** That URL satisfies `observed_live_claude_result` and un-skips `test_live_claim_requires_an_observed_claude_result`.

The adapter CLI (`python -m coordination.claude_adapter --live`) is unchanged and still refuses. Wiring this runner into the CLI should happen together with items 1–3, not before.
