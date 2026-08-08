# CALYX-455 — Mission Control harvester command center

Status: IMPLEMENTED / GOVERNED REVIEW-ONLY

## Delivered

- Stable Mission Control projection over the existing BUILD-049 harvester control plane.
- Live operator cards for state, schedule, checkpoint, next run, last attempt, last success/failure, progress/yield, recommendation, warnings, errors, and allowed actions.
- iPad-safe versioned response envelope with bounded recent-run history and no credential/secret fields.
- Read-only previews for run-once, pause, resume, cancel, reschedule, retire, restore, and reassess.
- Preview proves both control-plane state and run history are unchanged and never invokes provider execution.
- Explicit confirmation required for every mutation; reschedule, retire, and restore additionally require an exact high-risk confirmation phrase.
- Run-once adapter intentionally calls the existing control plane with `execute=False`, producing a governed queue request without provider scraping from the command-center request path.
- Protected command adapters reuse existing control-plane methods and therefore preserve constitutional authorization decisions.
- Stable error codes for unsupported actions, missing harvesters, rejected commands, missing schedules, and confirmation failures.
- Operator readiness contract explicitly reports authorization, preview, confirmation, secret-exposure, provider-scraping, deployment, and production-test-mutation boundaries.
- Deterministic no-write, state-transition, confirmation, iPad-contract, queue-only, readiness, and protected-route tests.

## Governance boundaries

This slice does not expose secrets, weaken authentication, scrape external providers, authorize deployment or merge, or mutate production data from tests. The command center does not bypass the constitutional control plane. High-risk operations remain subject to both explicit operator confirmation and the pre-existing control-plane authorization decision.

## Validation

Dedicated CI compiles the command-center runtime/router/Mission Control surface, runs CALYX-455 tests plus the existing BUILD-049 control-plane regression suite, asserts permanent no-provider/no-production-test-mutation boundaries, runs Ruff, and checks diff hygiene. The PR remains draft/unmerged until exact-head CI and review gates are satisfied.
