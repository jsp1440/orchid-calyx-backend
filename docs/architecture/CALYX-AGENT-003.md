# CALYX-AGENT-003 — Preproduction Orchestrator

## Purpose

Provide a durable, restart-safe Calyx work queue for bounded audits and improvement planning without granting autonomous production authority.

## Implemented preproduction slice

- PostgreSQL-backed jobs and findings.
- Priorities, dependencies, attempts, leases, fencing tokens, completion, cancellation, and blocked-approval states.
- Seven-job overnight profile covering capability inventory, Brain, Mission Control, journalism, archive, harvesters, and deployment readiness.
- Read-only job allowlist.
- Governed Calyx-agent execution with optional external synthesis.
- Findings deduplication by stable fingerprint and provenance capture.
- Mission Control-facing status, recent jobs, active work, blocked approvals, and findings.
- Disabled-by-default worker process.

## Preproduction configuration

The worker will not start unless both variables are present:

```text
CALYX_ORCHESTRATOR_ENABLED=true
CALYX_ORCHESTRATOR_MODE=preproduction
```

Recommended preproduction settings:

```text
CALYX_ORCHESTRATOR_POLL_SECONDS=10
CALYX_ORCHESTRATOR_LEASE_SECONDS=300
CALYX_WORKER_ID=calyx-preproduction-1
```

External synthesis remains optional and requires the CALYX-AGENT-002 provider variables. The worker runs deterministic planning when no provider is configured.

## Activation sequence

1. Merge only after all focused and regression checks pass.
2. Apply `migrations/20260801_calyx_agent_003.sql` to a preproduction database.
3. Deploy one preproduction worker with the worker disabled.
4. Verify `/brain/orchestrator/status` and seed the overnight profile manually.
5. Enable one worker and observe lease, completion, findings, retries, and blocked approvals.
6. Increase concurrency only after the single-worker certification passes.

## Hard boundaries

The orchestrator cannot autonomously merge, deploy, migrate, alter production data, spend funds, activate production schedules, or publish canonical scientific knowledge. Requests requiring those actions are blocked for owner or scientific approval.

## Not yet production-complete

- No cron scheduler automatically seeds jobs.
- No multi-worker concurrency controller beyond database claim fencing.
- No lease-renewal heartbeat for jobs longer than the initial lease.
- No automatic GitHub issue or draft-PR creation.
- No production deployment configuration is included.
