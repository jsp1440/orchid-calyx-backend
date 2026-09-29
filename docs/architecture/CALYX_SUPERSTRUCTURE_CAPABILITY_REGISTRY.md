# Calyx Superstructure: Capability Registry Contract

Status: implementation slice for #1127, Plane C of #1123.

## Purpose

The superstructure needs to know two different things about every autonomous role:

1. **What is this role permitted to do?**
2. **How has this role actually performed?**

Those questions must never collapse into one another.

The existing `AuthoritativeExecutorRegistry` remains the canonical allowlist for execution authority. This capability-memory layer adds owner-scoped empirical performance context from durable `CalyxProgramJob` history.

## Non-negotiable rule

**Performance can change routing preference, never privilege.**

A role does not earn new permissions because it succeeds repeatedly. Likewise, a historical role that is no longer registered does not regain eligibility because its old runs were successful.

## Static authority

Every currently registered executor exposes its existing canonical flags:

- role key;
- executor key;
- authoritative registration;
- external-side-effect permission;
- workspace-mutation permission;
- repository-code-execution permission.

The capability projection derives an authority ceiling only from those static flags:

- `A0` — observe/read/validate without mutation;
- `A2` — bounded workspace mutation;
- `A3` — bounded repository-code execution when explicitly registered;
- `DISALLOWED_EXTERNAL_SIDE_EFFECTS` — never eligible through this registry;
- `NONE` — historical role not currently registered.

This is descriptive metadata, not a new authorization mechanism. The executor registry must still be checked at execution time.

## Empirical performance

For each role, owner-scoped durable history provides:

- observed job count;
- observed program count;
- terminal outcome count;
- successful terminal count (`DELIVERED` or `NO_OP`);
- descriptive historical success rate;
- outcome distribution;
- total attempts and retry count;
- average attempts per job;
- blocker distribution;
- human-escalation count;
- authoritative-receipt coverage;
- observed executor keys;
- last-observed timestamp.

A success rate is explicitly labeled `historical_observation_not_predictive_certainty`. It is a routing signal, not a guarantee.

## Historical unregistered roles

Durable program history can contain roles that are not present in today's authoritative registry. Those records remain useful institutional memory, but their profile is forced to:

- `registration_state = historical_unregistered_role`;
- `authoritative = false`;
- `eligible_for_autonomous_execution = false`;
- `authority_ceiling = NONE`.

No quantity or quality of historical success can restore registration automatically.

## Owner isolation

The empirical loader joins `CalyxProgramJob` through `CalyxProgram` and filters on the authenticated owner before aggregation. Performance from another owner cannot influence the current owner's routing context.

## Initial API

Owner-authenticated read surface:

`GET /programs/capability-registry`

This endpoint is declared before the generic `/{program_id}` route so the static capability path cannot be interpreted as a program identifier.

## Meta-orchestrator use

Plane D may consume the capability projection to choose among **already eligible** roles. A safe routing sequence is:

1. identify required capability and consequence level;
2. restrict candidates to currently registered/eligible roles;
3. consider empirical outcome, retry, blocker and escalation history;
4. choose the minimum sufficient team;
5. immediately before execution, call the canonical `AuthoritativeExecutorRegistry.require_authoritative()` boundary again;
6. refuse any operation beyond the role's static authority ceiling.

The capability-memory projection can help decide *which permitted worker to use*. It can never decide *what a worker is permitted to do*.
