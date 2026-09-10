# Swarm Economy Controller v1

Status: implementation on `oc-autonomous-integration`; paid execution remains owner-gated.

## Goal

Maximize completed, tested Orchid Continuum work per dollar rather than minimizing raw API-call count.

The controller prepares work before a paid model is invoked, limits context, runs free deterministic diagnostics first, reserves spend conservatively, routes to the least-expensive justified model tier, allows only one paid provider in a workflow run, and records economics around durable task completion.

## Execution funnel

```text
queue
  -> compact work packet
  -> deterministic preflight
  -> model-tier router
  -> NO_API_MODE gate
  -> execution governor
  -> one paid provider
  -> validation / PR
  -> conservative spend accounting
  -> bounded retry classification
  -> next task
```

## Work packets

`runtime/swarm/work_packet.py` and `scripts/swarm_prepare_work_packet.py` build a deterministic packet from the issue title, body and labels.

The packet:
- deduplicates repeated issue text;
- caps the issue summary;
- extracts acceptance criteria, hard constraints and likely file paths;
- fingerprints the material task;
- estimates prompt size;
- references durable repository instructions instead of copying them into every prompt.

This intentionally avoids asking a provider to rediscover the whole repository for every issue.

## Deterministic-first diagnostics

`scripts/swarm_deterministic_preflight.py` runs before paid reasoning.

It never executes issue-supplied commands and never edits files. It only performs fixed allowlisted checks on explicit file hints, including Python compilation and JSON parsing where applicable. Results are included in the provider work packet so the model does not need to spend turns rediscovering simple failures.

## Cost-aware model routing

`scripts/oc_model_router.py` continues to select the cheapest Claude tier justified by task evidence and now emits a conservative pre-run cost reservation.

Defaults:

| tier | max turns | reservation |
|---|---:|---:|
| cheap | 24 | $0.50 |
| standard | 45 | $1.25 |
| deep | 75 | $2.00 |

These are safety reservations, not billing claims. They are configurable with repository variables.

## Provider policy

Economy Controller v1 deliberately permits only one paid provider execution per completion-lane workflow run.

Automatic Claude -> Gemini -> OpenAI chaining is disabled in the completion lane because multiple providers in one run can consume spend faster than durable accounting is refreshed.

Provider diversity remains available through separately governed workflows and can later be reintroduced through a one-provider-per-run provider router after measured canary economics are available.

## Governor hardening

Paid execution now requires all of the following:

- `NO_API_MODE` explicitly permits providers;
- `OC_GOVERNOR_PAID_EXECUTION_ENABLED=true`;
- emergency kill switch is off;
- provider is explicitly allowlisted;
- retry count is within the configured limit;
- per-run estimate is present and valid;
- per-run, daily and monthly budgets are present, positive and valid;
- projected spend remains within every budget.

Missing, malformed, negative or non-finite monetary configuration fails closed.

Probe mode is not execution authority.

## Spend accounting

`scripts/swarm_governor_postrun.py` prefers provider-reported actual cost when available. If actual cost is unavailable, it records the conservative reservation rather than silently treating the run as free.

Provider-side account/project spending limits remain the strongest hard backstop; repository-side accounting is an orchestration safety layer and must not be represented as a substitute for provider billing controls.

## Retry policy

`runtime/swarm/retry.py` classifies failures before another model call is considered:

- CI/runner/network-transient -> retry workflow without consuming a model retry;
- deterministic lint/compile/test failure -> deterministic repair path;
- reasoning/implementation/max-turns -> at most one model repair;
- security/billing/budget/provider/unknown -> stop fail-closed.

## Success metric

The primary efficiency metric is:

```text
actual provider spend / successfully completed durable task
```

A task counts as completed only when the provider result produced durable work (normally a PR) and the required validation path succeeds.

Do not optimize for API-call count alone.

## Initial rollout

1. Keep `NO_API_MODE` closed while CI validates this controller.
2. Merge only to `oc-autonomous-integration` after independent checker evidence.
3. Configure provider-side hard spend limits.
4. Configure governor budgets and allowlist exactly one provider.
5. Run issue #1085 as the first single-worker canary.
6. Review cost, turns, prompt size, elapsed time, validation outcome and durable PR result.
7. Run several tasks sequentially before considering concurrency > 1.
8. Expand only when measured cost per completed task remains acceptable.

No production deployment, scientific publication, taxonomy activation, credential change or spending authorization is implied by this document.
