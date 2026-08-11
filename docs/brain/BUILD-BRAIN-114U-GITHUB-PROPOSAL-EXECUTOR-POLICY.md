# BUILD-BRAIN-114U — GitHub Proposal Executor Policy Registration

**Status:** implementation candidate; disabled by default; no credential activation.

## Purpose

Register the validated GitHub draft-PR proposal adapter behind an explicit fail-closed policy boundary without weakening the existing `AuthoritativeExecutorRegistry`, whose internal authoritative roles remain prohibited from external side effects.

## Policy contract

Configuration is intentionally disabled by default.

- `CALYX_GITHUB_PROPOSAL_EXECUTOR_ENABLED` — must be explicitly true.
- `CALYX_GITHUB_PROPOSAL_EXECUTOR_OWNER` — exact authorized owner principal; required when enabled.
- `CALYX_GITHUB_PROPOSAL_REPOSITORIES` — comma-separated exact repository allowlist; required when enabled.

Credential material is not configured by this slice. A separate secret-preserving `CredentialReadiness` boundary exposes only a boolean readiness result. No token value is accepted into status payloads, logs, evidence, or the Brain.

## Construction gates

`GovernedGitHubProposalExecutorRegistration.build_executor(...)` fails closed unless all of the following are true:

1. executor policy is explicitly enabled;
2. exact owner matches the configured owner;
3. target repository is in the configured allowlist;
4. the injected credential-readiness boundary reports ready.

Only then can the registration construct the already-governed `GitProposalMutationExecutor` with the validated GitHub proposal adapter and durable mutation journal.

The registration is deliberately separate from `AuthoritativeExecutorRegistry`. This preserves the registry invariant that autonomous internal executors have no external side effects and avoids silently converting existing worker roles into network-mutating roles.

## Truthful status

The status surface exposes only non-secret readiness information:

- enabled/disabled;
- owner configured boolean;
- exact allowed repositories;
- credential ready boolean;
- blockers;
- readiness for owner-authorized draft PR execution;
- fixed `autonomy/proposal/` namespace;
- draft-PR-only scope;
- explicit false authority for force push, branch deletion, merge/auto-merge, deployment, publication, taxonomy activation, production database mutation, production Knowledge Graph mutation, credential disclosure, and spending.

## Governance boundary

This implementation does **not**:

- install, read, persist, expose, or activate a real GitHub token or GitHub App credential;
- register the executor into the deployed runtime;
- turn on the feature flag in any environment;
- perform live GitHub mutation;
- merge or auto-merge;
- deploy;
- mutate production databases or the production Knowledge Graph;
- publish science, promote Candidate Knowledge, or activate taxonomy;
- grant secret or spending authority.

Actual credential configuration and live runtime activation remain a separate explicit owner-governed action.
