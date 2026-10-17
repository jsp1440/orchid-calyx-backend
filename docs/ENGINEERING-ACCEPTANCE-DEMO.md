# Governed engineering cycle: first verified cycle, then ten

Status: **prepared, not run.** Every step that spends money, changes repository variables, or authorizes work is the owner's.

## What counts as one engineering cycle

`scripts/oc_engineering_acceptance_report.py` judges each issue from the GitHub records the existing engine writes. A cycle passes only when all five criteria hold, each bound to the **same attempt**.

| # | Requirement | Record checked, and what binds it to the attempt |
|---|---|---|
| 1 | Governed acquisition | A bot `oc.swarm-claim.v1` lease claim. Its `lease_id` must equal `repo:worker_run:worker_attempt:issue` from the settlement, and the claim must come before the settlement. |
| 2 | Authorized dispatch to a real model | A bot `[OC-AUTO] Completion worker started … model=…` comment after that claim, naming the settled worker run. No admission denial may name that lease. |
| 3 | Engineering work | The bot's own draft PR: branch `claude-direct/issue-<n>-<run>`, body `OC-AUTO-ISSUE: #<n>`, the settled head, a non-empty diff. |
| 4 | Exact-commit tests and an independent checker | **Tests:** the `orchid-autonomous-validation` run the settlement relied on is green. That is the bot `workflow_dispatch` run on the PR branch at the head, started after the worker, with the highest run id. **Checker:** a PASS `OC-CHECKER-EVIDENCE-V1` record at that head, with `maker_id = anthropic:maker:<worker_run>:<n>` and checker `anthropic:checker:<run>:<n>`. |
| 5 | Verified merge and durable receipt | Exactly one bot `OC-HOSTED-SETTLEMENT-V1` receipt. GitHub must confirm all of the following: the PR is merged into `oc-autonomous-integration`; its `merge_commit_sha` equals the receipt's; the merge commit's two parents include the head; and `compare` shows the merge on the branch. The issue must be closed `completed` with `oc-done`. |

These never count:
- a heartbeat;
- a denied admission;
- a provider-free or acquisition-lane claim;
- a mock;
- a record written by a person (every agent shares the owner's identity).

Claims that never reached a provider are listed as zero-execution, with the engine's reason. A provider attempt that ran and never settled is a **failure**. A later re-claim cannot hide it.

- `--window-start <UTC>`: GitHub lists every issue claimed since then.
- `--first-cycle`: exits 0 when the latest finished cycle passed. It never certifies.
- Certification (ten consecutive cycles plus one lease recovery) requires window mode. A caller-chosen `--issues` list never certifies.

## Canonical path (on `main`; no new engine)

1. The controller (`orchid-swarm-controller.yml`, every 5 minutes) runs coding admission (`swarm_governor_precheck.py`), then the planner, then the lease claim.
2. The completion lane (`orchid-completion-lane.yml`, one global paid slot) routes the work (`oc_model_router.py`), runs the per-run governor precheck, then `swarm_anthropic_direct.py`, and opens a draft PR into `oc-autonomous-integration`.
3. `orchid-autonomous-validation.yml` runs at the head.
4. `oc-convergence-supervisor.yml` (`oc_hosted_completion.py`) runs:
   - the owner's factory authorization;
   - one checker call (claude-haiku-4-5, a separate identity);
   - the factory gate;
   - `PUT pulls/{pr}/merge` pinned to the head, read back;
   - the settlement receipt and `oc-done`.

The Gemini and OpenAI fallbacks are disabled in the lane (`if: ${{ false }}`). The `calyx-program-autonomy.yml` cron is gated off. The Render worker is a read-only program loop. The ACS Claude adapter is not on this path.

## The first task

**"Bottleneck report must not assert an unobserved 'next bottleneck'"**

`runtime/bottlenecks.py` (served through `CalyxHeartbeat`) always ends with "Next bottleneck is live CDS integration." That is a claim nobody observed.

- **Allowed paths:** `runtime/bottlenecks.py` and a new `tests/test_runtime_bottlenecks.py`.
- **Labels:** `oc-queued`, `oc-model-cheap`.
- **Capability:** `OC-SWARM-CAPABILITY: open-ended-code-authoring`.
- **Rehearsal results (local):**
  - The real planner (`oc_swarm_controller.py --worker-slots 1 --coding-executor`) selects it for the provider lane (`provider_launch_count: 1`).
  - The router gives tier `cheap`, `claude-haiku-4-5`, 24 turns.
  - The engine's `authorization()` accepts the record shape and refuses one by a bot or an edited one.
  - A throwaway reference solution passes the specified tests, so the spec is solvable within its two files.

## Spend bound: what each limit actually controls

| Limit | Where enforced | What it bounds |
|---|---|---|
| Model and tier | `oc-model-cheap` label, plus `OC_CLAUDE_MAXIMUM_TIER=cheap` (passed to the router by this PR) | Every attempt, **including a repair**, uses claude-haiku-4-5 ($1 input / $5 output per million tokens, 200K context). Without the cap, a repair escalates to claude-sonnet-5 (1M context). |
| Turns and output | `swarm_anthropic_direct.py` (hard-coded) | At most 24 calls, each with `max_tokens` ≤ 3072 and a 120 s timeout. The lane job times out at 70 minutes. |
| Attempts | `OC_GOVERNOR_MAX_RETRIES=1` | The first attempt plus one repair. **0 is not usable:** the controller's coding admission hardcodes `retry_count=1`, so 0 would refuse all coding work. |
| Checker | `oc_hosted_completion.py` | One call (`checker_calls: 1`), a prompt of at most 48 KB, `max_tokens` 1800. |
| Repository budgets | `OC_GOVERNOR_PER_RUN/DAILY/MONTHLY_BUDGET_USD` against the issue-#1330 ledger | **Admission only, on reservation estimates** (cheap $0.50 per maker run, checker $0.08). Controller admission reserves the highest tier estimate ($2.00), so the per-run budget must be ≥ $2.00. October already has **$10.00** reserved. These are **not** a billing cap. |
| Hard dollar cap | Anthropic Console: the workspace spend limit for the key in `ANTHROPIC_API_KEY` | The only limit that stops provider billing. It cannot be verified from this repository. |

**Worst case by construction** for one cycle with these settings:
- per maker attempt: 24 × 200K input × $1/M ≈ $4.80, plus 24 × 3,072 output × $5/M ≈ $0.37, which is about $5.17;
- two attempts: about $10.34;
- checker: under $0.05;
- total ceiling: **about $10.40**.

The expected cost is far lower, because a two-file change uses a small fraction of the context.

## Window, kill switch, rollback

- **Window:** opens when paid execution is enabled. Closes at the first settlement, at the first failed attempt that is not a repair, or after 3 hours, whichever comes first.
- **Kill switch:** `NO_API_MODE=true` blocks the next precheck. A call already in flight finishes its current step (at most 120 s per call).
- **Rollback:** restore `NO_API_MODE=true` and `OC_GOVERNOR_PAID_EXECUTION_ENABLED=false`, and put `oc-queued` back on #1742.
- **Recovery:** the merge into `oc-autonomous-integration` is a normal merge commit. It can be reverted on that branch, and `main` is never touched.

## Evidence

```
python3 scripts/oc_engineering_acceptance_report.py \
  --repository jsp1440/orchid-calyx-backend \
  --window-start <window open, UTC> --first-cycle --output acceptance-report.json
```

The report links the claim, worker run, PR head, validation run, checker record and settlement receipt for the cycle.
