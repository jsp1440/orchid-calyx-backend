from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ApprovedTask:
    domain: str
    job_type: str
    priority: int
    title: str
    request_text: str
    read_only: bool = True
    requires_owner_approval: bool = False


# Reviewed, safe, unattended work reservoir.  Active lane width is intentionally
# much smaller than this list: completion/block/wait must return to this reservoir
# and immediately select the next eligible task.  Keep tasks bounded, evidence-
# producing, non-destructive, and below protected owner boundaries.
APPROVED_TASKS = (
    ApprovedTask("calyx_finish_line", "mission_control_audit", 1, "Audit Calyx owner finish line", "Measure the exact remaining gaps before the owner can ask Calyx where the Continuum stands and then hold a grounded scientific conversation on phone/iPad."),
    ApprovedTask("taxonomy", "capability_inventory", 10, "Audit taxonomy readiness", "Inspect taxonomy storage, staging, smoke certification, crosswalk, impact, promotion blockers, and rollback readiness."),
    ApprovedTask("calyx_runtime", "deployment_readiness", 11, "Audit Calyx runtime truth", "Verify canonical runtime state, registered routes, persistence, provider status, and degraded-mode truthfulness."),
    ApprovedTask("calyx_research_executor", "capability_inventory", 12, "Audit Calyx research executor", "Verify queued_waiting_for_executor through completed/blocked transitions, exactly-once claims, replay, artifacts, and feedback."),
    ApprovedTask("calyx_scientific_reads", "capability_inventory", 13, "Audit canonical scientific reads", "Verify taxonomy, occurrence, elevation, traits, literature, ecological relationship, and provenance reads are canonical and read-only."),
    ApprovedTask("calyx_acceptance", "mission_control_audit", 14, "Audit Calyx acceptance mission", "Verify one real read-only orchid mission reaches canonical evidence, synthesis, citations, uncertainty, immutable artifact, and replay."),
    ApprovedTask("owner_calyx_mobile", "website_design_audit", 15, "Audit Owner Calyx mobile experience", "Inspect phone/iPad conversation shell, persistent sessions, streaming, citations, uncertainty, live status, and degraded states."),
    ApprovedTask("owner_calyx_context", "mission_control_audit", 16, "Audit Owner Calyx program context", "Verify Calyx can read bounded repository, CI, provider, completion-graph, module, blocker, and owner-gate context."),
    ApprovedTask("research_station_persistence", "archive_readiness", 17, "Audit Research Station persistence", "Inspect durable request/result persistence, provenance records, immutable artifacts, idempotency, and canonical storage defaults."),
    ApprovedTask("research_station_retrieval", "capability_inventory", 18, "Audit Research Station retrieval", "Inspect arbitrary-taxon literature/evidence retrieval, query planning, source attribution, snippets, and failure states."),
    ApprovedTask("meta_orchestrator", "brain_audit", 19, "Audit consequence-aware meta-orchestrator", "Inspect minimum-sufficient specialist planning, consequence classes, authority gates, capability registry use, and human-gated high consequence."),
    ApprovedTask("knowledge_graph", "brain_audit", 20, "Audit Knowledge Graph quality", "Inspect coverage, contradictions, orphan nodes, unsupported edges, stale sources, and provenance gaps."),
    ApprovedTask("experience_ledger", "brain_audit", 21, "Audit Experience Ledger", "Inspect empirical outcome capture, replayable evidence, failure learning, provider outcomes, and planning feedback."),
    ApprovedTask("epistemic_memory", "brain_audit", 22, "Audit epistemic memory", "Inspect source/inference/memory distinctions, contradiction handling, confidence, uncertainty, and provenance."),
    ApprovedTask("capability_registry", "capability_inventory", 23, "Audit capability registry", "Verify canonical capabilities, roles, provider requirements, authority, costs, health, and endpoint bindings."),
    ApprovedTask("completion_graph", "mission_control_audit", 24, "Audit recursive completion graph", "Inspect bounded leaves, acceptance evidence, dependencies, priorities, owner/external blockers, and stale/superseded state."),
    ApprovedTask("deep_orchestrate", "mission_control_audit", 25, "Audit deep orchestrate reservoir", "Verify a deep prioritized reservoir exists beyond active lane width with stable keys, dedupe, dependencies, acceptance, and governance metadata."),
    ApprovedTask("lane_refill", "mission_control_audit", 26, "Audit no-idle lane refill", "Verify eligible safe capacity is immediately refilled after completion, block, provider wait, or CI wait."),
    ApprovedTask("duplicate_suppression", "mission_control_audit", 27, "Audit duplicate suppression", "Inspect material-change fingerprints, issue/PR head dedupe, repeated dispatch suppression, and unchanged-run prevention."),
    ApprovedTask("lease_atomicity", "mission_control_audit", 28, "Audit lease atomicity", "Verify queued-to-running transition is atomic before execution and stale/expired leases are reclaimed safely."),
    ApprovedTask("repair_backoff_backend", "deployment_readiness", 29, "Audit backend repair-backoff invariant", "Verify repair-backoff cannot be queued, leased, healed, dispatched, or terminally requeued across every workflow path."),
    ApprovedTask("matrix", "mission_control_audit", 30, "Audit Relationship Matrix", "Inspect evidence coverage, unavailable dimensions, neighborhood quality, and relationship-path explanations."),
    ApprovedTask("repair_backoff_frontend", "deployment_readiness", 31, "Audit frontend repair-backoff invariant", "Verify repair/runtime backoff cannot be re-admitted by healer, scheduler, dispatcher, or settlement paths."),
    ApprovedTask("provider_failover", "deployment_readiness", 32, "Audit provider failover", "Verify Claude/Gemini/OpenAI fallback is bounded, fail-closed on security, redacted, non-thrashing, and provider-independent in governance."),
    ApprovedTask("exact_head_ci", "deployment_readiness", 33, "Audit exact-head CI", "Verify merge decisions use current exact head and reject stale, skipped, cancelled, action_required, or non-substantive checks."),
    ApprovedTask("integration_promotion", "deployment_readiness", 34, "Audit integration-to-main gates", "Inspect integration/main drift, owner-gated promotion PRs, production risk, branch protection, and deployment coupling."),
    ApprovedTask("deployment_reconciliation", "deployment_readiness", 35, "Audit production deployment reconciliation", "Identify serving platform, repository, branch, SHA, domain routing, deployed artifact, and drift without changing production."),
    ApprovedTask("frontend_contracts", "deployment_readiness", 36, "Audit frontend/backend contracts", "Inspect route parsing, schema compatibility, degraded states, auth boundaries, and stale endpoint assumptions."),
    ApprovedTask("mission_control", "mission_control_audit", 37, "Audit Mission Control", "Inspect queue, active lanes, next actions, blockers, exact-head CI, provider health, owner gates, and mobile readability."),
    ApprovedTask("atlas", "capability_inventory", 38, "Audit Atlas", "Inspect canonical map data, occurrence/elevation queries, locality protection, Mapbox/Google Earth integration readiness, and provenance."),
    ApprovedTask("literature", "capability_inventory", 39, "Audit Literature module", "Inspect search, PDF metadata, extraction, evidence spans, citations, methods/results/conclusions, and arbitrary orchid taxa."),
    ApprovedTask("identification", "journalism_readiness", 40, "Audit orchid identification", "Inspect observation coverage, candidate retrieval, conflicts, look-alikes, and expert-review pathways."),
    ApprovedTask("pollinator", "capability_inventory", 41, "Audit Pollinator module", "Inspect interaction evidence, candidate pollinators, literature linkage, phenology, uncertainty, and provenance."),
    ApprovedTask("mycorrhizal", "capability_inventory", 42, "Audit Mycorrhizal module", "Inspect fungal relationship evidence, UNITE linkage, provenance, uncertainty, and no-fabricated-absence behavior."),
    ApprovedTask("interaction_graph", "brain_audit", 43, "Audit Interaction Graph", "Inspect orchid-pollinator-fungus-host edges, evidence, confidence, contradiction, provenance, and locality controls."),
    ApprovedTask("traits", "capability_inventory", 44, "Audit trait integration", "Inspect EOL/TraitBank and canonical trait ingestion, normalization, provenance, conflicts, and unavailable states."),
    ApprovedTask("occurrence", "capability_inventory", 45, "Audit occurrence integration", "Inspect GBIF/iNaturalist/iDigBio ingestion, dedupe, coordinates, elevation, provenance, freshness, and sensitive-locality policy."),
    ApprovedTask("taxonomy_sources", "capability_inventory", 46, "Audit taxonomy sources", "Inspect World Plants, WFO, IPNI, POWO, Tropicos crosswalks, synonymy, identifiers, provenance, and activation separation."),
    ApprovedTask("orchid_roots", "harvester_readiness", 47, "Audit OrchidRoots integration", "Inspect available hybrid/lineage data access, normalization, provenance, licensing constraints, and canonical mapping."),
    ApprovedTask("rhs", "harvester_readiness", 48, "Audit RHS integration", "Inspect grex/registration data access, identifiers, normalization, provenance, licensing, and uncertainty."),
    ApprovedTask("bhl", "harvester_readiness", 49, "Audit BHL integration", "Inspect historical literature discovery, OCR/text metadata boundaries, citations, provenance, and image/document linkage."),
    ApprovedTask("brain", "archive_readiness", 50, "Audit Brain reasoning", "Inspect evidence, Candidate Knowledge, contradiction, confidence, validation, review, and publication boundaries."),
    ApprovedTask("globi", "harvester_readiness", 51, "Audit GloBI integration", "Inspect ecological interaction ingestion, taxon reconciliation, provenance, confidence, and contradictory relationships."),
    ApprovedTask("eol", "harvester_readiness", 52, "Audit EOL integration", "Inspect TraitBank/entity linkage, identifiers, provenance, freshness, and mapping to canonical orchids."),
    ApprovedTask("unite", "harvester_readiness", 53, "Audit UNITE integration", "Inspect fungal taxonomy/sequence linkage, orchid mycorrhizal mapping, provenance, uncertainty, and locality concerns."),
    ApprovedTask("inat", "harvester_readiness", 54, "Audit iNaturalist harvester", "Inspect cursoring, idempotency, batch state, dedupe, photos, observations, geoprivacy, and provenance."),
    ApprovedTask("gbif", "harvester_readiness", 55, "Audit GBIF harvester", "Inspect occurrence paging, dataset provenance, basis-of-record, coordinates/elevation, licensing, and dedupe."),
    ApprovedTask("idigbio", "harvester_readiness", 56, "Audit iDigBio harvester", "Inspect specimen retrieval, identifiers, collector/locality controls, media linkage, provenance, and dedupe."),
    ApprovedTask("image_taxonomy", "journalism_readiness", 57, "Audit Image and Taxonomy", "Inspect image provenance, taxon matching, confidence, duplicates, rights, and expert-review boundaries."),
    ApprovedTask("vision_lab", "journalism_readiness", 58, "Audit Vision Lab", "Inspect orchid image analysis, feature extraction, evidence retention, uncertainty, and expert-review pathways."),
    ApprovedTask("matrix_id", "journalism_readiness", 59, "Audit Matrix ID", "Inspect candidate ranking, diagnostic traits, conflicts, missing dimensions, provenance, and explanation paths."),
    ApprovedTask("integration", "deployment_readiness", 60, "Audit cross-repository integration", "Inspect Brain, backend, and frontend contract compatibility, route availability, and degraded states."),
    ApprovedTask("lexicon", "education_readiness", 61, "Audit Lexicon", "Inspect botanical terms, scientific definitions, linking, citations, ambiguity, and integration with Calyx/University."),
    ApprovedTask("university", "education_readiness", 62, "Audit University", "Inspect curriculum graph, lessons, labs, assessments, scientific accuracy, source citations, and adaptive pathways."),
    ApprovedTask("conservatory", "capability_inventory", 63, "Audit Conservatory", "Inspect living-collection records, accession identity, culture data, images, provenance, and Calyx linkage."),
    ApprovedTask("conservation_portal", "capability_inventory", 64, "Audit Conservation Portal", "Inspect threat/status evidence, locality protection, project/research linkage, uncertainty, and publication gates."),
    ApprovedTask("scientific_memory", "brain_audit", 65, "Audit Scientific Memory", "Inspect durable scientific claims, evidence lineage, methods intelligence, contradictions, review state, and publication separation."),
    ApprovedTask("methods_intelligence", "brain_audit", 66, "Audit Methods Intelligence", "Inspect experimental methods extraction, protocol normalization, source linkage, applicability, uncertainty, and review."),
    ApprovedTask("legacy_archaeology", "archive_readiness", 67, "Audit legacy archaeology", "Inventory recoverable legacy apps/widgets/repos, exact paths/commits, canonical equivalents, reuse value, and security/scientific concerns."),
    ApprovedTask("fcos_judging", "archive_readiness", 68, "Audit legacy orchid judging capability", "Assess recoverable judging implementation, scientific standards, current canonical destination, and safe reuse path."),
    ApprovedTask("scientific_method_widget", "archive_readiness", 69, "Audit scientific-method teaching assets", "Assess recoverable research teaching experience, content provenance, current University fit, and safe reuse path."),
    ApprovedTask("website", "website_design_audit", 70, "Audit website design", "Inspect accessibility, UX, navigation, information architecture, and scientific visualization."),
    ApprovedTask("hollywood_orchids", "archive_readiness", 71, "Audit Hollywood Orchids assets", "Assess recoverable movie/orchid widget content, source provenance, rights, canonical destination, and safe reuse path."),
    ApprovedTask("security_gateway", "deployment_readiness", 72, "Audit agent security gateway", "Inspect tool authority, input/output validation, prompt-injection boundaries, redaction, and fail-closed behavior."),
    ApprovedTask("auth", "deployment_readiness", 73, "Audit authentication boundaries", "Inspect owner/API authentication, browser/server key separation, route protection, session handling, and degraded behavior."),
    ApprovedTask("sensitive_locality", "brain_audit", 74, "Audit sensitive-locality controls", "Inspect field-level suppression, inference leakage, map output, research artifacts, exports, and owner gates."),
    ApprovedTask("provenance", "brain_audit", 75, "Audit provenance end-to-end", "Trace representative scientific assertions from source through ingestion, storage, graph, synthesis, citation, and UI."),
    ApprovedTask("unknown_semantics", "brain_audit", 76, "Audit unknown/unavailable semantics", "Verify missing data never becomes biological absence or zero across API, graph, matrix, Calyx, and UI."),
    ApprovedTask("idempotency", "deployment_readiness", 77, "Audit idempotency", "Inspect harvesters, research execution, queue dispatch, artifacts, replay, and duplicate event handling."),
    ApprovedTask("observability", "mission_control_audit", 78, "Audit observability", "Inspect structured logs, correlation IDs, queue transitions, provider diagnostics, redaction, and operator-facing failure truth."),
    ApprovedTask("mobile_accessibility", "website_design_audit", 79, "Audit mobile accessibility", "Inspect iPhone/iPad navigation, touch targets, text sizing, keyboard/screen reader behavior, and responsive scientific views."),
    ApprovedTask("education", "education_readiness", 80, "Audit education systems", "Inspect University models, curriculum alignment, lessons, assessments, and virtual-laboratory gaps."),
    ApprovedTask("performance", "website_design_audit", 81, "Audit frontend performance", "Inspect bundle/runtime bottlenecks, image loading, map rendering, caching, degraded networks, and mobile responsiveness."),
    ApprovedTask("image_loading", "website_design_audit", 82, "Audit image loading", "Inspect broken image paths, provenance/rights metadata, fallback states, caching, and responsive rendering."),
    ApprovedTask("mapbox", "deployment_readiness", 83, "Audit Mapbox readiness", "Inspect existing map integration, key boundary, style/source wiring, occurrence layers, and locality-policy enforcement without adding credentials."),
    ApprovedTask("google_earth", "deployment_readiness", 84, "Audit Google Earth readiness", "Inspect canonical integration options, data/export contracts, locality-policy controls, and credential requirements without adding credentials."),
    ApprovedTask("api_cost_policy", "deployment_readiness", 85, "Audit model cost policy", "Inspect provider/model routing defaults, escalation thresholds, token accounting, spending gates, and non-spending canaries."),
    ApprovedTask("scientific_acceptance", "mission_control_audit", 86, "Audit scientific acceptance harness", "Verify representative orchid dossiers assert evidence, provenance, uncertainty, no fabricated absence, and sensitive-locality protection."),
    ApprovedTask("release_acceptance", "deployment_readiness", 87, "Audit release acceptance", "Inspect preproduction acceptance, rollback evidence, owner gates, deployment drift, and protected production boundaries."),
    ApprovedTask("brain_reconciliation", "brain_audit", 88, "Audit Brain reconciliation", "Inspect mission graph, engineering memory, scientific memory, current completion graph, stale decisions, and superseded architecture."),
    ApprovedTask("repo_inventory", "archive_readiness", 89, "Audit canonical repository inventory", "Discover all current and legacy Orchid Continuum repositories, roles, default/integration branches, deployments, and canonical ownership."),
    ApprovedTask("harvesters", "harvester_readiness", 90, "Audit harvesters", "Inspect source freshness, failures, duplication, schedules, licensing, and schema drift."),
    ApprovedTask("dependency_graph", "mission_control_audit", 91, "Audit cross-repository dependency graph", "Inspect blocking edges, false serialization, safe parallelism, critical path, and owner/external blockers."),
    ApprovedTask("parallel_capacity", "mission_control_audit", 92, "Audit parallel execution capacity", "Inspect global/repository slot limits, provider concurrency, lane fairness, CI waiting behavior, and opportunities to safely increase throughput."),
    ApprovedTask("queue_depth", "mission_control_audit", 93, "Audit queue depth", "Measure eligible reservoir depth by priority/module and identify why safe capacity could become idle."),
    ApprovedTask("next_action_projection", "mission_control_audit", 94, "Audit next-action projection", "Verify every blocked/completed lane exposes deterministic next eligible work and Mission Control can display it."),
    ApprovedTask("artifact_registry", "archive_readiness", 95, "Audit artifact registry", "Inspect immutable build/research/evidence artifacts, hashes, provenance, retention, and links to issues/PRs/results."),
    ApprovedTask("data_licensing", "brain_audit", 96, "Audit scientific data licensing", "Inspect source licenses/terms, attribution requirements, redistribution constraints, and UI/export compliance."),
    ApprovedTask("backup_recovery", "deployment_readiness", 97, "Audit backup/recovery readiness", "Inspect non-production backup assumptions, restore documentation, rollback boundaries, and production-gated operations."),
    ApprovedTask("documentation_truth", "archive_readiness", 98, "Audit documentation truth", "Identify stale architecture/status docs, reconcile with code/runtime evidence, and mark superseded material without deleting history."),
)

PROHIBITED_AUTONOMOUS_ACTIONS = {
    "merge_pull_request",
    "deploy_production",
    "run_production_migration",
    "promote_taxonomy",
    "publish_scientific_knowledge",
    "send_external_communication",
    "spend_money",
    "delete_canonical_data",
}


def task_profile() -> tuple[ApprovedTask, ...]:
    return tuple(sorted(APPROVED_TASKS, key=lambda task: (task.priority, task.domain)))


def validate_task(task: ApprovedTask) -> None:
    if not task.read_only:
        raise ValueError("AUTONOMOUS_TASK_MUST_BE_READ_ONLY")
    if task.requires_owner_approval:
        raise ValueError("APPROVAL_TASK_CANNOT_RUN_UNATTENDED")
    if task.priority < 1:
        raise ValueError("INVALID_PRIORITY")


def task_provider_status() -> dict[str, object]:
    tasks = task_profile()
    for task in tasks:
        validate_task(task)
    return {
        "provider": "reviewed-static-v3-deep-reservoir",
        "mode": "preproduction",
        "task_count": len(tasks),
        "tasks": [task.__dict__ for task in tasks],
        "prohibited_actions": sorted(PROHIBITED_AUTONOMOUS_ACTIONS),
        "production_activation": False,
        "scientific_publication_authority": False,
    }
