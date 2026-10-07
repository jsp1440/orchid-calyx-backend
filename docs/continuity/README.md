# Orchid Continuum Continuity Layer

This directory is the low-cost startup surface for coding agents working on Orchid Continuum.

It complements, rather than replaces, `docs/AGENT-OPERATING-MEMORY.md` and the Engineering Memory service. Durable memory records lessons that should survive sessions. The continuity layer records the small amount of **live operational state** a fresh session needs before deciding what must be re-verified.

## Startup contract

1. Read `CURRENT_STATE.yaml`.
2. Read `NEXT_ACTIONS.yaml` when selecting or continuing work.
3. Read `docs/AGENT-OPERATING-MEMORY.md` for durable corrections relevant to the task.
4. Verify only mutable facts required by the requested work: current branch/HEAD, PR state, required checks, reviews, deployment/runtime evidence, or other facts that may have changed.
5. Do not perform a broad repository audit merely to reconstruct history already represented here. Expand discovery only when this state is stale, contradictory, incomplete for the task, or contradicted by repository evidence.
6. Repository code, tests, GitHub state, hosted evidence, and explicit owner decisions outrank this layer when they conflict.

## Truth classes

Every live claim should be distinguishable as one of:

- `verified`: supported by exact evidence identified in the record.
- `observed`: directly observed, but not sufficient to certify the larger capability.
- `candidate`: proposed or reported, awaiting verification.
- `blocked`: a named gate prevents advancement.
- `unknown`: not established; never infer success from absence.

## Update rule

A bounded engineering increment should update this layer only when it changes a cross-session fact worth carrying forward. Keep it compact. Do not copy raw prompts, conversations, secrets, protected locality data, or large logs here.

For exact-head work, record the SHA and the evidence that applies to that SHA. Evidence from an older head remains historical and must not be silently promoted to a newer head.

## Relationship to existing memory

- `AGENTS.md`: mandatory operating/governance rules.
- `docs/AGENT-OPERATING-MEMORY.md`: durable corrections learned from repeated failures.
- Engineering Memory v1 (`app/engineering_memory/`): retrievable scoped engineering lessons with provenance and invalidation.
- `docs/continuity/`: compact current orientation, active gates, and next safe actions.

The design goal is **verify deltas, not rediscover the system**.
