# Agent Coordination System — ACS-001

Hub: https://github.com/jsp1440/orchid-calyx-backend/issues/1823

## Intent and boundaries
Eliminate owner-mediated report transfer through durable machine-readable GitHub messages and an independent coordinator. Run without importing Calyx, app.main or app.database. No model calls, shell execution, workflow dispatch, merge, deployment, credential provisioning or scientific publication exists in this runtime. Actions outside safe engineering remain owner-gated. User explicitly authorized independent design, implementation and tests on 2026-10-13; routine design handoff approvals are waived by that instruction.

## Audit, 2026-10-13
- Backend main inspected at 6444eb696f46ed57daf5c45b6abed8c19e3ee471. Hub initially had zero comments; a protocol alone is not a running subscriber.
- Existing .github/workflows/orchid-continuation-supervisor.yml wakes the canonical scheduler. Existing completion/swarm workflows can invoke providers; ACS must not dispatch them under current authorization.
- app/calyx_orchestrator/github_agent_dispatch_store.py persists Calyx job dispatches but imports app.database and is bound to Calyx job lifecycles. Reuse its identity/transition conventions, not its production database bootstrap.
- AGENTS.md, AGENT-OPERATING-MEMORY.md, AGENT-SECURITY-BOUNDARIES.md and SOFTWARE-FACTORY-V1.md reviewed. Do not make a second scheduler for scientific jobs: ACS transports engineering assignments and reports only.
- Open-PR inventory and coordination branch search inspected. FIL #1808/#1810 are read-only capability contracts, not this transport. Graph #1819, TraitBank #1811 and lazy repository #1827 are separate lanes; their paths stay untouched. No dedicated ACS PR was identified in the returned inventory.
- Render My Workspace: Calyx srv-d65otolum26s73ef316g live, auto-deploy main, 1 GB /var/data disk. Acceptance worker srv-db67bgo473hc73ddmt90 suspended by user, auto-deploy off, on Claude's autonomy branch. Do not resume or repoint it without authorization. FCOS workspace contains legacy Orchid_Continuum_Online, not canonical backend.
- Neon oc-autonomy-acceptance jolly-field-40713887 has only default branch br-solitary-dream-ar701d70 named production. Compute ep-odd-shape-ar0ssh5g idle. No SQL executed and no compute started. Other listed projects: orchid-continuum, OC3, calyx-show-management. Metadata inventory does not establish schema compatibility or authorization for writes.

## Options
1. GitHub-only workflow aggregator: avoids DB provisioning but mutable comments are poor transactional leases, schedules may be delayed, and existing workflows may spend credits.
2. Independent service with transactional store and GitHub transport (selected): SQLite for local/disposable proof; PostgreSQL for later reuse of Neon after approved isolated schema setup. Existing Render process capacity can be assessed before selecting hosting; no new service is created here.
3. Extend Calyx dispatch store: maximizes code reuse but violates initial Calyx independence and risks import-time production connections.

## Contracts
An event has a version, stable event_id, kind, task_id and exact kind-specific fields. GitHub comments hold one fenced JSON object after [OC-ACS-v1]. Only configured GitHub numeric user IDs may submit messages; owner identity is separate from agent identity. Unknown keys and kinds fail closed. Same id/same payload is a no-op; same id/different payload is an error. Github records are data, never instructions to execute shell commands.

Assignments: owner/coordinator only, one immutable task identity (agent, objective reference and action). Safe action is engineering. merge, deploy, production_db, paid_ai, infrastructure and scientific_publish park in owner_gate and cannot be claimed, even after acknowledgement; this version deliberately has no privileged executor. Owner approves/rejects exact task and digest, with expiry. Acknowledgement is an auditable decision, not a production capability.

Agent protocol: claim -> lease token -> heartbeats -> response with the same token. A replacement lease invalidates old workers. Completion is delivered (maker report, not checker acceptance) or blocked. Heartbeats extend liveness but a hard attempt deadline prevents infinite occupancy. Missing executor is represented by the unclaimed task state; no fabricated heartbeat or success.

## Persistence and recovery
Dedicated acs_* tables hold events, tasks, agent health and a transactional outbox. All mutations serialize under BEGIN IMMEDIATE (SQLite) or a transaction-scoped PostgreSQL advisory lock. Commit receipt state and report together. Retries use deterministic exponential backoff, max 3 attempts by default; no sleeping transaction. Heartbeat expiry recovers task to retry or dead_letter. Outbox delivery claims expire after crashes and tokens fence stale acknowledgements. Event and generated-report IDs use separate namespaces. A final uncertain delivery enters reconciliation-only recovery, confirming an existing marker without permitting another POST beyond the send budget. GitHub delivery is at least once; stable markers and full paginated comment reconciliation suppress sequential reposts after uncertain responses. Concurrent/out-of-band publishers can still duplicate comments; consumers deduplicate event IDs.

SQLite requires a persistent local disk and one host. Ephemeral Render filesystem is not durable storage. PostgreSQL uses dedicated COORDINATOR_DATABASE_URL, never ambient DATABASE_URL, and explicit migration only. No startup schema creation.

## Agent reachability
ChatGPT/Claude/Kimi/Copilot names are routing identities, not callable endpoints. Connected account tools in this session do not provide background execution of their consumer chats. Agents with a GitHub-reading session can consume assignment comments and post the protocol; automatic wake-up needs a separately configured authenticated adapter. Calyx later implements the same claim/heartbeat/response interface. ACS neither promises nor enables a five-agent autonomous loop before these adapters are verified.

## Security and public reporting
GitHub allowlist IDs come from private operator configuration, never comment payloads. Reporter posts only state/reason/task/agent/action plus stable marker; objective references, lease tokens, responses and credentials are not mirrored. Tasks refer to safe GitHub issue/PR URLs, not arbitrary prompt text. GitHub token gets issues read/write only for the allowlisted repository. No arbitrary URLs, redirects or remote code execution. Raw webhook signatures and trusted principal mapping are required for direct ingress; untrusted GitHub authors cannot grant owner approval.

## Validation and activation
Prove restart recovery, concurrent claims, duplicate/conflicting events, expired/stale leases, owner spoofing, bounded retries, response fencing, transactional outbox recovery and fake-GitHub end-to-end flow. Local tests are distinct from hosted CI and live agent execution. Before activation: independent review on exact head, approved persistent host/schema, least-privilege GitHub token, verified agent identity bindings, adapter reachability and owner authorization. Rollback stops process; additive acs_* tables are isolated from scientific state. Never automatically delete evidence.
