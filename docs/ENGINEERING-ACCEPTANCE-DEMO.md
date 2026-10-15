# Governed engineering demonstration: ten independently validated cycles

Status: **prepared, not run.** Every step that spends money, changes repository variables or authorizes work is marked **OWNER**. Claude does none of those steps.

## What counts

A cycle counts only if all five of these are true. `scripts/oc_engineering_acceptance_report.py` checks each one against GitHub records the existing engine already writes:

| # | Requirement | Record checked |
|---|---|---|
| 1 | Governed task acquisition | `[OC-SWARM-V4] Dependency/resource lease claimed` (`oc.swarm-claim.v1`), posted by `github-actions[bot]` |
| 2 | Authorized dispatch to a real executor | `[OC-AUTO] Completion worker started … model=…` after that claim, with no `Provider admission denied` after it |
| 3 | Engineering work performed | The maker PR named by the settlement, at the settled head, with a non-empty diff |
| 4 | Independent validation at the exact head | `orchid-autonomous-validation` succeeded at that head SHA, and an `OC-CHECKER-EVIDENCE-V1` record shows PASS for that head, with required checks passed and `checker_id` a different actor from `maker_id` (`same_actor`) |
| 5 | Durable completion receipt | `OC-HOSTED-SETTLEMENT-V1` from the bot with a verified merge SHA, and the issue closed `completed` with label `oc-done` |

The run is **certified** only when there are ten consecutive passing cycles, ordered by settlement time, and at least one of them recovered an expired lease (`oc.swarm-lease-recovery.v1`). Each zero-execution outcome must carry the engine's own reason.

These never count as a cycle:
- a heartbeat;
- provider-free validation (for example #1782);
- a denied admission (for example #1401, with 126 denied or backoff events, every one with a reason);
- a record written by a person.

A record written by a person matters because every agent shares the owner's GitHub identity.

## Canonical path (exists on `main`; no new engine)

The flow runs left to right. Each stage is a workflow or script that already exists on `main`:

1. **Lease.** `orchid-swarm-controller.yml` runs every 5 minutes, under one concurrency group, and claims a lease on an issue.
2. **Execute.** `orchid-completion-lane.yml` runs with global paid concurrency of 1. It calls `swarm_governor_precheck.py` with `OC_GOVERNOR_PROVIDER: anthropic`, then `swarm_anthropic_direct.py`, which uses the model from `oc_model_router.py`.
3. **Draft PR.** The maker opens a draft PR into `oc-autonomous-integration`.
4. **Validate.** `orchid-autonomous-validation.yml` runs at that head.
5. **Check and settle.** `oc-convergence-supervisor.yml`, through `oc_hosted_completion.py`:
   - the checker runs on Claude Haiku as a different identity;
   - the factory gate decides;
   - the merge is verified;
   - it posts `OC-HOSTED-SETTLEMENT-V1`.
6. **Recover.** `oc_swarm_lease_reconcile.py` releases dead leases based on run evidence.

The Render worker (`orchid-calyx-autonomy`) is a separate, read-only program loop. It replenishes work through proposals (#1840) and does not dispatch engineering work. The `calyx-program-autonomy.yml` cron is gated off by `CALYX_PROGRAM_AUTONOMY_ENABLED` (latest run 38662471638 skipped). So exactly one scheduler dispatches engineering work: the swarm controller.

## Preconditions

1. **OWNER: merge #1787 into `main`.** On `main`, a paid run with an empty provider skips the allowlist (`swarm_governor_precheck.py:140`).
2. **OWNER: fast-forward `oc-autonomous-integration` to `main`.** The completion lane checks out that branch and opens PRs against it. The hosted checker requires it, and it is 88 commits behind `main` (an ancestor, so a fast-forward is enough and no force-push is needed):
   ```
   git fetch origin && git push origin origin/main:refs/heads/oc-autonomous-integration
   ```
3. **OWNER: bound the controller.** Set the variable `OC_SWARM_WORKER_SLOTS=1` (added in this PR). Scheduled waves then lease one lane instead of eight, so lanes aren't queued and then cancelled under the shared paid concurrency group.
4. **OWNER: limit the queue to the demonstration.** Only the ten demonstration issues may carry `oc-queued`, `oc-repair` or `oc-runtime-backoff`. Today these are open:
   - `oc-queued`: #1742;
   - `oc-repair`: #1730, #1729, #1725, #1724, #1722, #1721, #1717 and #1396.

   Park them (for example with `oc-blocked`) for the window, or accept that the budget below also covers them.
5. **OWNER: create ten small issues.** Each should be a low-risk, repository-local change with one obvious test, for example a narrow validation or a missing unit test. Each gets its own `OC-HOSTED-FACTORY-AUTHORIZATION-V1` comment, written by the owner and never edited, containing:
   ```
   <!-- OC-HOSTED-FACTORY-AUTHORIZATION-V1
   {"repository":"jsp1440/orchid-calyx-backend","issue":<n>,"issue_material":"<digest of title+body>",
    "target":"oc-autonomous-integration","checker_calls":1,"risk":"low",
    "expires_at":"<UTC, about 48 h out>","allowed_paths":["<1-12 repo paths>"]}
   -->
   ```
   `issue_material` is `oc_hosted_completion.issue_material(issue)`. Claude can compute it for each issue. Only the owner may post the record: `authorization()` refuses any author who isn't the owner, and any edited comment.
6. **OWNER: set the spend controls.** These are repository variables:

   | Variable | Value for the window |
   |---|---|
   | `OC_GOVERNOR_PROVIDER_ALLOWLIST` | `anthropic` |
   | `OC_GOVERNOR_PER_RUN_BUDGET_USD` | for example `2.00` |
   | `OC_GOVERNOR_DAILY_BUDGET_USD` | for example `25.00` |
   | `OC_GOVERNOR_MONTHLY_BUDGET_USD` | for example `40.00` |
   | `OC_GOVERNOR_MAX_RETRIES` | `1` |
   | `OC_GOVERNOR_EMERGENCY_KILL_SWITCH` | empty |

   The secret `ANTHROPIC_API_KEY` must belong to an account that has an organisation-level spend limit.

## Activation (OWNER, explicit)

Set `OC_GOVERNOR_PAID_EXECUTION_ENABLED=true` and `NO_API_MODE=false`. The 5-minute schedule then picks up the queue. No other trigger is needed.

**Kill switch:** set `NO_API_MODE=true`, or set `OC_GOVERNOR_EMERGENCY_KILL_SWITCH=true`. Either one blocks the next precheck. A run already in progress finishes its current step.

**Timeout:** each lane has its own `timeout-minutes`, and a lease whose run is dead is recovered by reconciliation.

## Controlled recovery (part of the ten)

Once one demonstration lane is running, cancel that workflow run from the Actions UI. The next controller wave records `oc.swarm-lease-recovery.v1` and requeues the issue. When that issue later completes, it is the recovered cycle.

## Evidence

After the window closes:

```
python3 scripts/oc_engineering_acceptance_report.py \
  --repository jsp1440/orchid-calyx-backend --issues <the ten numbers> \
  --output acceptance-report.json
```

- The command exits 0 only when the run is certified.
- Keep `acceptance-report.json` in the demonstration PR and as a workflow artifact. Each cycle links its claim, worker run, PR, validation run, checker record and settlement receipt.
- Then return to `NO_API_MODE=true` and `OC_GOVERNOR_PAID_EXECUTION_ENABLED=false`.

Until that report says `"certified": true`, unattended engineering execution is **not** demonstrated.
