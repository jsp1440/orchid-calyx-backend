# CALYX-AGENT-GOV-001 — governed coding-agent intent and behavior

Issue: #1239

## Purpose

This slice adds the minimum provider-neutral least-agency primitives needed to make broader autonomous engineering safer without creating a second governance system. It complements the existing `ConstitutionalMissionOrchestrator` and `AgentSecurityGateway`.

## Task Intent Contract

`TaskIntentContract` records the autonomous task identity, mission, repository/base identity, objective, allowed paths and tools, explicit forbidden actions, validation commands, related issue/PR identities, cost ceiling, and owner-gate state. Its canonical SHA-256 fingerprint includes material task state and the current head SHA. Provider/model identity is deliberately excluded, so changing from Claude to Codex/Gemini/Azure cannot widen authority or manufacture a new task identity.

The fingerprint is suitable for unchanged-work suppression: the same task contract at the same material repository head yields the same value; an objective, scope, base/head, validation, issue/PR identity, or budget change yields a different value.

## Agent Behavioral Ledger

`AgentBehaviorLedger` is append-only and records a safe structured decision trace: task/mission/fingerprint, agent and provider provenance, behavior kind, action/resource/tool identity, policy decision, reason, cost, and bounded caller-supplied metadata.

It intentionally has no field for raw prompts, model chain-of-thought, tool argument values, credentials, environment values, or secret material.

## Least-agency enforcement

`LeastAgencyGuard` is deterministic and task-scoped. The first rules are deliberately small and fail closed:

- self-expansion of authority is prohibited;
- writes to protected agent/governance paths are prohibited;
- tools and writable paths outside the task contract are prohibited;
- explicit forbidden actions are prohibited;
- privileged mutation/network actions after external/untrusted content ingestion are blocked;
- outbound network activity following sensitive-file access is blocked;
- task cost ceilings are enforced;
- safe reversible writes inside declared task scope remain allowed when no anomaly is present.

These rules are an additive foundation, not a claim that prompt-injection risk is solved. Dispatcher binding and durable persistence are follow-up work after this repository-local contract is validated.

## Boundaries

This slice does not deploy, migrate a database, change secrets, change repository permissions, merge automatically, mutate canonical scientific truth, publish scientific content, or weaken existing owner gates.
