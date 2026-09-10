# Swarm Governor — Canary Preparation: Issue #1085

**Status:** PREPARED — do NOT execute without explicit owner authorization.

This document captures the exact policy and prerequisite state required to run
issue #1085 as the first controlled canary under the Swarm Execution Governor.
It is a planning document only. No provider call, dispatch, or activation is
initiated by this document.

---

## Issue #1085 profile

- **Purpose:** First real paid execution under governor control (canary)
- **Recommended provider:** Anthropic Claude (lowest blast radius; most mature tooling)
- **Why #1085:** Small, bounded scope; does not touch production DB, taxonomy,
  or scientific data; does not require deploy access; can be reviewed as a draft PR.
- **Verify before proceeding:** Confirm issue #1085 is still open, has an `oc-queued`
  label, and does not carry `oc-repair-backoff`, `oc-runtime-degraded`, or any
  credential-touching label.

---

## Required policy state (GitHub Variables)

Set these repository variables before enabling the canary. All values are strings.

| Variable | Required value | Purpose |
|---|---|---|
| `NO_API_MODE` | `false` | Enable paid execution |
| `OC_GOVERNOR_EMERGENCY_KILL_SWITCH` | (absent or `false`) | Kill switch must be off |
| `OC_GOVERNOR_PAID_EXECUTION_ENABLED` | `true` | Full governor enforcement |
| `OC_GOVERNOR_PROVIDER_ALLOWLIST` | `anthropic` | Only Claude for canary |
| `OC_GOVERNOR_PER_RUN_BUDGET_USD` | `2.00` | Max cost per run (conservative) |
| `OC_GOVERNOR_DAILY_BUDGET_USD` | `5.00` | Daily ceiling |
| `OC_GOVERNOR_MONTHLY_BUDGET_USD` | `20.00` | Monthly ceiling |
| `OC_GOVERNOR_MAX_RETRIES` | `1` | Canary: single retry max |
| `OC_GOVERNOR_DAILY_SPEND_USD` | `0` | Reset before canary |
| `OC_GOVERNOR_MONTHLY_SPEND_USD` | `0` | Reset before canary |
| `OC_GOVERNOR_LAST_RUN_DATE` | today (YYYY-MM-DD UTC) | Baseline |
| `OC_GOVERNOR_LAST_RUN_MONTH` | this month (YYYY-MM UTC) | Baseline |

---

## GovernorPolicy snapshot for #1085 canary

```python
GovernorPolicy(
    paid_worker_concurrency=1,          # enforced by GitHub concurrency group
    max_retries=1,
    stop_on_provider_error=True,
    stop_on_budget_threshold=True,
    auto_refill=False,                   # always False
    per_run_budget=Decimal("2.00"),
    daily_budget=Decimal("5.00"),
    monthly_budget=Decimal("20.00"),
    emergency_kill_switch=False,
    provider_allowlist=frozenset({"anthropic"}),
    provider_priority=("anthropic",),
    paid_execution_enabled=True,
)
```

---

## Pre-flight checklist (verify each before dispatch)

- [ ] `NO_API_MODE` is set to `false` in repo Variables
- [ ] `OC_GOVERNOR_EMERGENCY_KILL_SWITCH` is absent or `false`
- [ ] `OC_GOVERNOR_PAID_EXECUTION_ENABLED` is `true`
- [ ] `OC_GOVERNOR_PROVIDER_ALLOWLIST` is `anthropic` (only)
- [ ] Budget variables are set to conservative canary values (see table above)
- [ ] Spend counters reset to `0` with today's date/month
- [ ] CI is green on `oc-autonomous-integration` (no pre-existing failures)
- [ ] PR #1325 (Swarm Execution Governor) is merged to `oc-autonomous-integration`
- [ ] Issue #1085 is open, has `oc-queued`, lacks `oc-repair-backoff`
- [ ] Owner has explicitly authorized this canary execution in writing
- [ ] A second person (human or independent checker) is ready to monitor

---

## Execution plan (do NOT execute without authorization)

1. Set all GitHub Variables per the table above.
2. Manually dispatch `Orchid Completion Lane` workflow with `issue_number=1085`.
3. Monitor the run in the Actions tab:
   - Step "NO-API mode guard" should show `providers ALLOWED`
   - Step "Swarm governor precheck" should show `AUTHORIZED_PROBE_MODE` (or
     `AUTHORIZED` if `OC_GOVERNOR_PAID_EXECUTION_ENABLED=true`)
   - Step "Execute issue with Claude Code" runs
4. Review the draft PR opened by the workflow.
5. Do NOT merge or auto-integrate without independent checker pass + factory gate.

---

## Abort procedure

If the canary is running and must be stopped immediately:

1. Set `NO_API_MODE` to `enabled` in repository Variables (takes effect on
   any NEW run immediately).
2. Cancel the in-progress Actions run manually (Actions tab → Cancel workflow).
3. Set `OC_GOVERNOR_EMERGENCY_KILL_SWITCH` to `true` to block future runs.

Full procedure: `docs/SWARM-GOVERNOR-KILL-PROCEDURE.md`

---

## Post-canary review criteria

The canary is successful if ALL of the following are true:

- The workflow completed without exceeding the per-run budget.
- A draft PR was opened for issue #1085.
- The PR does not touch production DB, taxonomy, scientific records, credentials,
  or main branch.
- `OC_GOVERNOR_DAILY_SPEND_USD` was updated by `swarm_governor_postrun.py` (or
  the actual cost was manually verified from Anthropic billing console).
- No unexpected provider errors or circuit-breaker events on issue #1031.

If any criterion fails, set `OC_GOVERNOR_EMERGENCY_KILL_SWITCH=true` and file a
post-mortem before the next canary attempt.
