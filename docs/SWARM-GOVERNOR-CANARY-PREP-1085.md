# Swarm Governor — Canary Preparation

**Status:** ISSUE #1085 RETIRED AS CANARY — do not execute it as a provider canary.

## Correction

A current repository check shows issue #1085 is an `oc-owner-gate` P0 mission whose remaining acceptance criterion requires live production measurements / telemetry and explicit owner authority. It is therefore **not** an appropriate low-blast-radius provider canary.

Do not use #1085 to validate paid Swarm execution.

## Canary eligibility contract

The first real provider canary must be a current issue that is all of the following:

- open and explicitly runnable;
- not `oc-owner-gate`, `oc-blocked`, `oc-repair-backoff`, or `oc-runtime-backoff`;
- not already `oc-validating` with implementation delivered;
- reversible repository-local engineering only;
- no production deployment or production DB/KG mutation;
- no credentials/security-authority change;
- no spending action beyond the explicitly authorized provider call;
- no taxonomy/scientific-authority activation or scientific publication;
- no sensitive-locality exposure;
- small enough to finish in one bounded provider run;
- has objective tests / acceptance criteria and can yield a draft PR;
- has no existing authoritative implementation PR that should be converged instead.

If no current issue satisfies this contract, the truthful state is:

`CANARY_CANDIDATE_UNAVAILABLE`

Do not create artificial busywork merely to exercise the provider.

## Initial live policy once an eligible candidate exists

Use exactly one paid provider and one worker:

| Variable | Initial value |
|---|---|
| `NO_API_MODE` | `false` only for the authorized canary window |
| `OC_GOVERNOR_PAID_EXECUTION_ENABLED` | `true` |
| `OC_GOVERNOR_PROVIDER_ALLOWLIST` | one provider only |
| `OC_GOVERNOR_PER_RUN_BUDGET_USD` | conservative owner-approved ceiling |
| `OC_GOVERNOR_DAILY_BUDGET_USD` | conservative owner-approved ceiling |
| `OC_GOVERNOR_MONTHLY_BUDGET_USD` | conservative owner-approved ceiling |
| `OC_GOVERNOR_MAX_RETRIES` | `1` |
| `OC_GOVERNOR_EMERGENCY_KILL_SWITCH` | `false` during the canary |
| cross-provider fallback | disabled |
| paid-worker concurrency | 1 |

The Economy Controller must prepare a compact work packet and deterministic preflight before the provider step.

## Kill procedure

If provider usage is abnormal:

1. Set `NO_API_MODE` back to a blocking value for new runs.
2. Set `OC_GOVERNOR_EMERGENCY_KILL_SWITCH=true`.
3. Cancel any in-progress GitHub Actions provider run.
4. Verify no new provider workflow enters an authorized provider step.

See `docs/SWARM-GOVERNOR-KILL-PROCEDURE.md` for the full procedure.

## Post-canary acceptance

Do not expand concurrency after one successful call. First verify several sequential tasks and record:

- provider and model;
- work-packet fingerprint / estimated prompt size;
- turns;
- input/output tokens when available;
- elapsed time;
- actual cost when available, otherwise conservative reserved cost;
- tests / checker outcome;
- durable PR created or not;
- cost per successfully completed task.

Only measured evidence should justify raising concurrency or enabling another provider.

## Current candidate status

As of the correction that retired #1085, no replacement canary is named in this document. The scheduler / owner should select the next **naturally occurring eligible bounded engineering issue** that satisfies the contract above.

Do not reinterpret #1085 as eligible unless its owner-gated production acceptance criteria materially change and the issue is explicitly reclassified.
