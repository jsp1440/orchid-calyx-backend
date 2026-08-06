# Calyx Autonomous Engineering Blueprint

## Purpose

Calyx shall operate as a governed autonomous engineering and scientific organization for the Orchid Continuum. The owner supplies goals, priorities, scientific judgments, credentials, and approvals. Specialized agents perform bounded work, preserve evidence, coordinate dependencies, validate results, and escalate only when a genuine human decision is required.

This blueprint extends the existing Calyx orchestrator rather than replacing it. Existing queueing, leases, retries, dependency jobs, dead-letter handling, approval gates, and Mission Control status remain authoritative.

## Governing principles

1. No agent may publish scientific knowledge, activate a taxonomy release, mutate the production Knowledge Graph, merge protected work, deploy production, or expose secrets without the required policy gate.
2. Every job is bounded by repository, subsystem, allowed tools, source branch, acceptance criteria, runtime, retry limit, and escalation policy.
3. Every completed job produces evidence: branch, commit, pull request, tests, checks, artifacts, blockers, and next executable job.
4. Claims, inference, code changes, scientific interpretation, and publication remain distinct.
5. Duplicate branches and duplicate pull requests are prohibited when an authoritative work item already exists.
6. Agents communicate through durable jobs and artifacts, not through the repository owner acting as a prompt relay.
7. A failed or expired worker lease returns work to the queue safely.
8. Human review remains mandatory for scientific publication, production graph mutation, taxonomy activation, production deployment, and other owner-only actions.

## Organizational model

### Executive and governance agents

- **Engineering Director** — converts approved goals into dependency-aware build programs, assigns work, detects stalled programs, and maintains one authoritative status view.
- **Chief Scientist** — reviews scientific scope, evidence quality, contradictions, confidence, provenance, and publication readiness.
- **QA and Release Manager** — owns test policy, CI health, merge readiness, deployment readiness, rollback evidence, and release certification.
- **Security and Governance Engineer** — owns authentication, permissions, secrets, auditability, policy classes, and prohibited actions.

### Platform agents

- **Backend Engineer** — APIs, services, authentication integration, and service contracts.
- **Frontend Engineer** — public interface, Mission Control, accessibility, responsive behavior, and live-data presentation.
- **Database Engineer** — PostgreSQL schemas, migrations, indexing, durability, and query performance.
- **Build and DevOps Engineer** — GitHub Actions, lint, compilation, test repair, deployment workflows, and environment verification.
- **Operations Engineer** — Render and production health, scheduled workers, telemetry, incident handling, and rollback readiness.

### Scientific intelligence agents

- **Knowledge Graph Engineer** — graph schema, projections, reconciliation, traversal, validation, idempotency, and certification.
- **Brain Engineer** — planning, retrieval, aggregation, contradiction analysis, interpretation, Reasoning Ledgers, review, and publication eligibility.
- **Taxonomy Engineer** — Hassler/World Plants intake, comparison, nomenclature, synonymy, reconciliation, release review, and activation preparation.
- **Literature Extraction Engineer** — acquisition, parsing, extraction, semantic indexing, citations, checkpoints, and candidate-knowledge handoff.
- **Evidence and Provenance Engineer** — source identity, claim lineage, confidence, review hashes, supersession, withdrawal, and retraction lifecycle.
- **Chief Scientific Integration Engineer** — verifies that taxonomy, occurrences, images, literature, ecology, and conservation evidence resolve to canonical taxon identities.

### Biodiversity and analytical agents

- **Atlas Engineer** — occurrences, geospatial services, tiles, filters, range maps, hotspots, spatial indexes, and map performance.
- **Image and Vision Engineer** — licensed-image ingestion, canonical media bridging, quality control, deduplication, attribution, and vision services.
- **Matrix Identification Engineer** — characters, states, scoring, interactive keys, relationship matrices, uncertainty, and identification candidates.
- **Pollination and Ecology Engineer** — pollinators, ecological interactions, habitat, climate, phenology, and relationship evidence.
- **Mycorrhiza Engineer** — fungal evidence, host associations, provenance, uncertainty, and graph integration.
- **Conservation Engineer** — threats, status, protected areas, conservation actions, risk analysis, and evidence updates.
- **Harvester Engineer** — source connectors, checkpoints, bounded ingestion, retries, rate limits, raw persistence, and freshness monitoring.

### Product agents

- **Conservatory Engineer** — collection records, accessioning, labels, QR codes, locations, events, images, and plant dossiers.
- **OASIS Engineer** — culture observations, care schedules, greenhouse data, alerts, and grower decision support.
- **Research Station Engineer** — projects, notebooks, datasets, collaboration, reproducible analyses, and exports.
- **University Engineer** — curricula, lessons, laboratories, assessments, learner progress, and scientific teaching design.
- **Mission Control Engineer** — queues, dependencies, approvals, failures, evidence, deployments, and operator controls.
- **Grant and Funding Agent** — funding discovery, eligibility, deadlines, application evidence, drafting, and follow-up monitoring; it may draft but never submit without approval.
- **Documentation Engineer** — architecture records, API documentation, runbooks, user instructions, and decision logs.

## Job contract

Every autonomous engineering job must include:

- `program_id`
- `job_id`
- `agent_role`
- `repository`
- `subsystem`
- `goal`
- `acceptance_criteria`
- `base_ref`
- `authoritative_branch` when one exists
- `authoritative_pull_request` when one exists
- `dependencies`
- `policy_class`
- `allowed_actions`
- `prohibited_actions`
- `maximum_attempts`
- `lease_seconds`
- `timeout_seconds`
- `required_checks`
- `human_approval_gate`
- `result_contract`

Valid terminal outcomes are:

- `DELIVERED`
- `BLOCKED`
- `NO_OP`
- `CANCELLED`
- `DEAD_LETTER`

`DELIVERED` must include the commit, authoritative PR, tests, checks, changed capabilities, remaining dependencies, and next executable job.

## Program and dependency model

A program is a directed acyclic graph of jobs. Completion of one job automatically releases dependent jobs. Independent jobs may run concurrently, subject to repository and subsystem concurrency limits.

Initial concurrency policy:

- maximum six active jobs globally;
- maximum two active jobs in one repository;
- maximum one mutating job on the same authoritative branch;
- unlimited read-only audits only when infrastructure capacity permits;
- owner-only or review-required jobs do not consume an execution slot while awaiting approval.

The Engineering Director shall detect:

- expired leases;
- stalled jobs;
- repeated failures;
- duplicate PRs;
- dependency cycles;
- work completed on another branch;
- a downstream job released by a completed dependency;
- a program with no remaining executable job.

## Agent execution levels

### Level 0 — Observe

Read-only inventory, health checks, status collection, and evidence gathering.

### Level 1 — Prepare

Create plans, issues, candidate patches, tests, documentation, and draft PRs. No merge or deployment.

### Level 2 — Repair

Update an authoritative branch, fix CI, resolve bounded conflicts, rerun checks, and prepare merge evidence.

### Level 3 — Integrate

Merge only after policy, CI, review, and branch-protection requirements are satisfied.

### Level 4 — Deploy

Deploy only through an approved deployment policy with health verification and rollback evidence.

### Level 5 — Scientific publish

Publish only through existing scientific review and publication gateways. No autonomous bypass is permitted.

The initial system shall implement Levels 0 through 2. Levels 3 through 5 remain gated.

## Mission Control requirements

Mission Control must show:

- programs and percentage complete;
- active, queued, retrying, blocked, dead-letter, and completed jobs;
- assigned agent role;
- repository, branch, PR, commit, and checks;
- dependency graph and next released job;
- lease owner and expiry;
- exact blocker and responsible party;
- required human action;
- recent evidence and artifacts;
- concurrency utilization;
- deployment and publication gates.

The owner must not need to copy prompts between applications. A human action card must appear only when a credential, scientific judgment, legal decision, merge approval, production deployment, taxonomy activation, or publication approval is truly required.

## Initial implementation phases

### Phase 1 — Autonomous Engineering Core

Extend the existing orchestrator with:

1. an agent-role registry;
2. program and dependency records;
3. repository/branch/PR work identity;
4. six-slot concurrency enforcement;
5. completion-triggered dependent-job release;
6. durable result contracts;
7. stalled-job and duplicate-work detection;
8. Mission Control program status;
9. protected APIs to create, pause, resume, cancel, and inspect programs;
10. deterministic tests using mocked GitHub and deployment providers.

The first active roles are:

- Engineering Director;
- Build and DevOps Engineer;
- Frontend Engineer;
- Backend Engineer;
- Knowledge Graph Engineer;
- Brain Engineer.

### Phase 2 — Scientific and data agents

Add Taxonomy, Literature Extraction, Atlas, Harvester, Image and Vision, Matrix, Mycorrhiza, Pollination and Ecology, Conservation, Evidence and Provenance, and Chief Scientist roles.

### Phase 3 — Product agents

Add Conservatory, OASIS, Research Station, University, Mission Control, Documentation, Operations, and Grant and Funding roles.

### Phase 4 — Governed integration and deployment

Enable policy-controlled merge, deployment, rollback, taxonomy activation preparation, and scientific-publication preparation. Human approvals remain mandatory where specified.

## First executable demonstration

Create one six-job program with bounded fixture-backed work:

1. Build Engineer audits and repairs one failing CI workflow.
2. Backend Engineer verifies one protected API contract.
3. Frontend Engineer fixes one live-data presentation defect.
4. Knowledge Graph Engineer runs a bounded staging-readiness proof.
5. Brain Engineer runs a fixture-backed retrieval-to-ledger mission.
6. Engineering Director produces a consolidated program report.

Jobs 1 through 5 may run concurrently. Job 6 depends on all five. No production graph mutation, taxonomy activation, scientific publication, production deployment, or automatic merge is allowed during this demonstration.

## Success criteria

The autonomous engineering core is operational when:

- six independent jobs can be queued and claimed without owner relay;
- dependent work starts automatically after prerequisites complete;
- retries and expired leases recover without duplicate execution;
- each job produces one authoritative outcome and evidence set;
- blocked work asks for one explicit human action;
- Mission Control shows real-time program and job status;
- no prohibited action can occur without its policy gate;
- the owner can start a program once and return later to a consolidated result.
