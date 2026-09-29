# Swarm Execution Governor — Emergency Kill Procedure

This document describes how to immediately halt all Orchid Continuum paid
provider execution across all GitHub Actions runners. Execute these steps in
order. Each step takes effect within seconds for new runs; already-running jobs
complete unless manually cancelled.

---

## Level 1 — Soft kill: NO_API_MODE (primary kill switch)

**Effect:** Blocks all paid provider steps in all five governed workflows. New
runs are allowed to start but stop immediately at the NO-API guard step. Already-
running provider steps finish normally.

**How to set:**

1. Open the repository on GitHub.
2. Go to **Settings → Secrets and variables → Actions → Variables**.
3. Locate `NO_API_MODE` (create it if absent).
4. Set the value to anything that is NOT one of the disable values:
   `disabled`, `false`, `0`, `no`, `off`.
   Recommended value: `enabled` (or any non-empty non-disable string).
5. Click **Save**.

**Confirmation:** Within the next scheduled or triggered run of any provider
workflow, the NO-API guard step will print:
```
[OC-NO-API-GUARD] NO_API_MODE='enabled': providers BLOCKED (set NO_API_MODE=false to enable).
```
All subsequent provider steps will be skipped.

**To re-enable:** Set `NO_API_MODE` to `false` (or `disabled`, `0`, `no`, `off`).

---

## Level 2 — Hard kill: Emergency kill switch

**Effect:** Blocks all paid provider steps even if `NO_API_MODE` was already
disabled. Evaluated after NO_API_MODE by the governor precheck in workflows that
include it.

**How to set:**

1. Open the repository on GitHub.
2. Go to **Settings → Secrets and variables → Actions → Variables**.
3. Locate `OC_GOVERNOR_EMERGENCY_KILL_SWITCH` (create it if absent).
4. Set the value to `true`.
5. Click **Save**.

**Confirmation:** The governor precheck step will print:
```
::error::[OC-GOVERNOR-PRECHECK] BLOCKED: BLOCKED_KILL_SWITCH
```
and write `authorized=false` to GITHUB_OUTPUT, causing provider steps to be
skipped.

**To re-enable:** Set `OC_GOVERNOR_EMERGENCY_KILL_SWITCH` to `false` or delete
the variable.

---

## Level 3 — Cancel running jobs

The above variable changes affect **new runs only**. To immediately stop jobs
that are already executing:

1. Go to the repository's **Actions** tab on GitHub.
2. Click the running workflow.
3. Click **Cancel workflow** in the top-right.

Repeat for all in-progress runs across all five provider workflows:
- `Governed Claude Code`
- `Orchid Claude Runtime Canary`
- `Orchid OpenAI Runtime Canary`
- `Orchid Provider Recovery Canary`
- `Orchid Completion Lane`

---

## Verifying the kill took effect

After setting the variable, trigger a manual run of any provider workflow via
**Actions → [workflow name] → Run workflow**. The run should complete quickly
(< 30 s) and every step after the NO-API guard should show as skipped.

To confirm across all five workflows, check the most recent completed run of each
and verify the provider steps are marked "Skipped".

---

## Durable spend state (GitHub Variables)

The governor tracks cumulative spend in these repository variables (updated by
`scripts/swarm_governor_postrun.py` if `actions:write` is granted):

| Variable | Description |
|---|---|
| `OC_GOVERNOR_DAILY_SPEND_USD` | Cumulative spend today (UTC) |
| `OC_GOVERNOR_MONTHLY_SPEND_USD` | Cumulative spend this month (UTC) |
| `OC_GOVERNOR_LAST_RUN_DATE` | Date of last spend update (YYYY-MM-DD) |
| `OC_GOVERNOR_LAST_RUN_MONTH` | Month of last spend update (YYYY-MM) |

To reset the spend counters (e.g., after an emergency investigation):

1. Set `OC_GOVERNOR_DAILY_SPEND_USD` to `0`.
2. Set `OC_GOVERNOR_MONTHLY_SPEND_USD` to `0`.
3. Set `OC_GOVERNOR_LAST_RUN_DATE` to today's date (YYYY-MM-DD UTC).
4. Set `OC_GOVERNOR_LAST_RUN_MONTH` to this month (YYYY-MM UTC).

**Limitation:** `swarm_governor_postrun.py` uses `gh variable set` which requires
`actions:write` GITHUB_TOKEN scope. If the workflow does not grant this, spend
is not automatically tracked. In that case the operator must update these variables
manually after confirming the actual cost from the provider's billing console.

---

## Options for fully durable budget accounting

The current spend tracking approach (GitHub Variables + `gh variable set`)
requires `actions:write` scope and is best-effort. For environments where fully
reliable budget accounting is required, the following options are available:

| Option | Durability | Complexity | New production dependency? |
|---|---|---|---|
| GitHub Variables (current) | Best-effort (requires actions:write) | Low | No |
| Committed JSON file | Reliable but creates noise commits | Medium | No |
| GitHub Actions cache | Evictable, not guaranteed | Medium | No |
| Existing Neon/PostgreSQL | Fully durable, atomic | High | **YES** — requires owner authorization |
| External budget API service | Fully durable, purpose-built | Very high | **YES** — requires owner authorization |

If fully reliable budget enforcement is required beyond GitHub Variables, the
owner must explicitly authorize adding the appropriate datastore integration.

---

## Security reminders

- Do NOT set `NO_API_MODE=false` if providers should remain halted.
- Do NOT disable or weaken the governor precheck in workflow files.
- Do NOT commit or log credential values during investigation.
- Do NOT force-push or rewrite history on the target branch.
- The concurrency group `swarm-paid-execution-{repository}` is the cross-runner
  serialization mechanism. Do not remove or rename it without updating all five
  provider workflows simultaneously.
