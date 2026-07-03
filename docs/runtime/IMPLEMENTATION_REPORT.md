# Calyx Runtime v0.1 Implementation Report

## Purpose

Move Active Calyx from notebook prototypes toward production runtime services.

## Status

Prototype runtime package integrated with the FastAPI backend router registration.

## Runtime Loop

1. HealthMonitorService observes configured services.
2. BottleneckService identifies the top operational bottleneck.
3. GoalPlannerService selects one recommended next goal.
4. GovernanceService applies autonomy policy.
5. MissionReporterService creates a report.
6. RuntimeMemoryWriter records an operational journal event.

## FastAPI Integration

The backend app starts at `app/main.py` and registers the existing runtime router from `runtime/router_fastapi.py`.

Runtime endpoints:

- `GET /api/runtime/heartbeat`
- `GET /api/runtime/health`

## Approval Boundary

This version does not merge code, delete files, alter schemas, send emails, or publish scientific claims.

## Operational Note

`RuntimeMemoryWriter` writes heartbeat events to `calyx_runtime_journal.jsonl` in the process working directory. Production memory writes should go only to approved Engineering Memory tables.
