# CALYX-AUTONOMY-OPERATIONS-002

## Objective

Activate the merged durable Calyx orchestrator as a bounded, read-only scientific and platform-audit worker. This slice replaces the current `no-approved-task-provider` dead end with an explicit reviewed task provider and certifies one supervised worker.

## Priority policy

The provider must offer work in this order while eligible work exists:

1. taxonomy intake/readiness and release comparison;
2. Knowledge Graph integrity and missing relationships;
3. Relationship Matrix evidence coverage;
4. Orchid Identification evidence and feature coverage;
5. Brain reasoning/readiness;
6. website, accessibility, design, and homepage audits;
7. education and virtual-lab readiness;
8. frontend/backend contract drift;
9. harvester and archive readiness;
10. judging and awards support only when no scientific/platform work is available.

The legacy five-minute runtime must not select `optimize_awards` ahead of eligible scientific work.

## Task-provider contract

Each approved task declares:

- stable task type and idempotency key;
- read-only tool allowlist;
- priority and dependency set;
- bounded input scope;
- expected evidence and finding schema;
- timeout and maximum attempts;
- explicit prohibited actions;
- whether external synthesis is optional;
- owner and correlation identity.

Unknown tasks fail closed. The provider cannot create merge, deployment, migration, publication, taxonomy-promotion, spending, deletion, external-send, permission, or governance actions.

## Pilot runtime

- one worker;
- concurrency fixed at one;
- lease with heartbeat renewal;
- durable jobs and findings;
- deterministic fallback when OpenAI is unavailable;
- owner-authenticated start and stop;
- one supervised cycle before recurring scheduling;
- evidence artifact containing claimed/completed jobs, leases, findings, tool calls, provider mode, failures, and prohibited-action checks.

## Deployment boundary

This PR may add code, tests, migration verification, and a manual certification workflow. It must not apply migrations, alter Render variables, dispatch production workflows, start the durable worker, or change the already running legacy autoloop.

## Acceptance

One manually authorized certification cycle completes a high-priority approved read-only task, persists a deduplicated finding with provenance, renews its lease when necessary, performs no prohibited action, and exposes the result through Mission Control.