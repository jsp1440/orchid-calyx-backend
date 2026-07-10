from __future__ import annotations

DEPENDENCY_GRAPH: dict[str, list[str]] = {
    "mission_control": ["backend", "governance", "harvesters", "build_history"],
    "atlas": ["taxonomy", "occurrences", "integrations"],
    "species_explorer": ["taxonomy", "images_media", "occurrences", "knowledge_graph"],
    "knowledge_graph": ["taxonomy", "literature", "pollinators", "mycorrhiza", "atlas"],
    "literature": ["integrations", "runtime_jobs"],
    "pollinators": ["literature", "knowledge_graph", "integrations"],
    "mycorrhiza": ["literature", "knowledge_graph", "integrations"],
    "vision_lab": ["images_media", "taxonomy", "species_explorer", "knowledge_graph"],
    "grant_office": ["knowledge_graph", "evidence_exports", "partnership_generator"],
    "partnership_generator": ["executive_audit", "grant_office", "atlas", "knowledge_graph"],
    "harvesters": ["runtime_jobs", "integrations", "governance"],
    "runtime_jobs": ["backend", "governance"],
    "governance": ["constitutional_policies", "decision_ledger"],
    "build_history": ["github", "deployment_registry"],
    "recommendations": ["executive_state", "dependency_graph", "evidence"],
    "health": ["mission_control", "backend", "database"],
    "completeness": ["mission_control", "telemetry"],
    "integrations": ["connectors", "backend"],
}


def dependency_graph() -> dict[str, list[str]]:
    return {node: list(dependencies) for node, dependencies in DEPENDENCY_GRAPH.items()}


def reverse_dependencies(graph: dict[str, list[str]] | None = None) -> dict[str, list[str]]:
    graph = graph or dependency_graph()
    reverse: dict[str, list[str]] = {}
    for node, dependencies in graph.items():
        for dependency in dependencies:
            reverse.setdefault(dependency, []).append(node)
    return {node: sorted(dependents) for node, dependents in reverse.items()}

