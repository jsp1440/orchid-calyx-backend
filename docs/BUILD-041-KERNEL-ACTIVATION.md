# BUILD-041 Kernel Activation

## Architecture

BUILD-041 activates the Orchid Continuum Kernel without adding write authority. The implementation extends the BUILD-040 registry foundation with live-readiness fields, query services, dependency traversal, planning outputs, recommendations, governance aggregation, and future autonomy interfaces.

The new activation layer lives in `runtime.kernel_activation` and is exposed through additional read-only `/api/kernel/*` endpoints. Mission Control and Atlas are not redesigned or replaced.

## Registry Population

The Kernel continues to register applications, services, capabilities, integrations, builds, and governance. BUILD-041 adds operational metadata to registry objects:

- availability
- last heartbeat
- warnings
- confidence
- telemetry unavailable reason

When live telemetry is available from existing backend context, the registry records it as evidence. When it is unavailable, the Kernel records the reason explicitly instead of silently pretending health is known.

## Dependency Model

`KernelDependencyGraphService` builds relationships between:

- applications and services
- services and integrations
- capabilities and applications/services
- builds and prerequisite builds/services

The graph supports full graph reads and bounded traversal from an object id.

## Planning Engine

`CalyxKernelOrchestrator.planner()` returns planning-only outputs:

- recommended next build
- dependency ordering
- missing infrastructure
- missing integrations
- registry completion score
- service maturity score
- future autonomy interfaces

No execution, deployment, GitHub action, or production write is performed.

## Recommendation Engine

`CalyxKernelOrchestrator.recommendations()` lets Calyx reason over Kernel state and recommend:

- unhealthy system remediation
- disconnected integration validation
- blocked build follow-up
- deployment order
- dependency resolution
- registry completion
- telemetry improvements

Recommendations are advisory only.

## Integration Registry

Integrations now include provider, authentication state, capabilities, rate limits, last validation, and credential reference metadata. Credential references use `vault://` identifiers and do not expose secret values.

## Secrets Vault

`KernelSecretsVault` is a secure abstraction for references only. It never reads, stores, logs, or returns secret values. It is designed to support future Azure Key Vault, Google Secret Manager, AWS Secrets Manager, or equivalent providers.

## Governance

The Kernel aggregates governance status from the existing constitutional orchestrator:

- governance version
- missions
- policies
- decisions
- governance questions
- constitutional status

Mission Control can consume this through `/api/kernel/governance` in a future frontend build.

## Future Autonomous Architecture

The runtime endpoint exposes architecture-only interfaces:

- Planner
- Scheduler
- Task Queue
- Agent Registry
- Execution Pipeline
- Reasoning Context

These interfaces deliberately have no autonomous execution authority in BUILD-041.

## Migration Notes

Existing BUILD-040 endpoints remain available. New consumers should prefer the Kernel API for registry, governance, planning, and recommendations. Backend deployment is required to expose the expanded API. Frontend deployment is not required by this build.
