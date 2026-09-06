"""Machine-readable candidate matrix for open-source scientific system evaluation.

OC-COMPLETE-009 — Scientific Adapter Laboratory.

Evaluates biodiversity/scientific open-source systems for KEEP_AS_DEPENDENCY,
PORT_CONCEPT, FEDERATE, ADAPT, or REJECT against the Orchid Continuum
architecture. Decisions are based on public documentation and repository
inspection; no code is auto-imported, no license is violated, and no
credentials are consumed.

REUSE_DECISION values:
  KEEP_AS_DEPENDENCY  — add as a runtime dependency (licence compatible)
  FEDERATE            — integrate via API/data; do not copy source
  PORT_CONCEPT        — the algorithm or pattern is reused, not the code
  ADAPT               — fork-and-adapt under its licence
  REJECT              — not suitable; reason documented
  CANDIDATE_UNVERIFIED — initially promising; needs deeper evaluation
"""

from __future__ import annotations

import json
from typing import Any

SCHEMA_VERSION = "oc-adapter-candidate-matrix/v1"

# ---------------------------------------------------------------------------
# Candidate records
# ---------------------------------------------------------------------------

CANDIDATE_MATRIX: list[dict[str, Any]] = [
    {
        "system_id": "globi",
        "display_name": "Global Biotic Interactions (GloBI)",
        "url": "https://www.globalbioticinteractions.org",
        "repositories": [
            "globalbioticinteractions/globalbioticinteractions",
            "globalbioticinteractions/elton",
            "globalbioticinteractions/nomer",
        ],
        "license": "MIT / CC0 (data) / Apache-2.0 (tooling; varies by repo)",
        "roles": [
            "interaction_data_federation",
            "provider_specific_dataset_adapters",
            "interaction_term_normalization",
            "taxon_name_alignment",
            "provenance_citation",
            "dataset_qa_review_workflow",
        ],
        "reuse_decision": "FEDERATE",
        "decision_rationale": (
            "GloBI's primary value for OC is federated access to its versioned stable "
            "dataset exports and Web API, not copying its internal source. The provider "
            "adapter pattern (per-dataset configuration, interaction-type ontology mapping, "
            "taxon-name normalization via nomer) is worth porting as concept. "
            "GloBI is NOT primarily an LLM literature extractor — its text extraction is "
            "a small fraction of its documented capability; do not rely on it for that role."
        ),
        "orchid_relevance": "HIGH — contains pollinator and mycorrhizal interaction records for orchids",
        "already_integrated": True,
        "integration_notes": (
            "runtime.interaction_harvester (live API), "
            "runtime.globi_canonical_harvester (versioned stable dataset), "
            "app.calyx_conversation.interaction_discovery_ingest, "
            "app.interaction_discovery.service — all REVIEW_BOUND, no auto-publication"
        ),
        "security_risk": "LOW — public read-only API; no credentials required for data access",
        "reeval_on_release": True,
    },
    {
        "system_id": "gbif_name_api",
        "display_name": "GBIF Species API / Name Matching",
        "url": "https://www.gbif.org/developer/species",
        "repositories": ["gbif/gbif-api", "gbif/checklistbank"],
        "license": "Apache-2.0",
        "roles": ["canonical_taxon_name_resolution", "taxonomy_backbone", "synonym_lookup"],
        "reuse_decision": "FEDERATE",
        "decision_rationale": (
            "GBIF's species name matching API is the most widely used open canonical "
            "taxon-name reconciliation service. Federate via API; no source copy needed. "
            "Returns canonical usage key, accepted name, synonyms, and confidence score. "
            "Suitable as the taxon reconciliation stage in the GloBI proof pipeline."
        ),
        "orchid_relevance": "HIGH — GBIF is the primary source for orchid taxonomy backbone",
        "already_integrated": False,
        "integration_notes": "GloBI records carry GBIF taxon IDs; parsing them is already implemented in interaction_discovery_ingest.py",
        "security_risk": "LOW — public read-only API; registration optional for higher rate limits",
        "reeval_on_release": False,
    },
    {
        "system_id": "nomer",
        "display_name": "nomer (GloBI taxon name matcher)",
        "url": "https://github.com/globalbioticinteractions/nomer",
        "repositories": ["globalbioticinteractions/nomer"],
        "license": "MIT",
        "roles": ["taxon_name_alignment", "batch_name_resolution", "name_matching_pipeline"],
        "reuse_decision": "PORT_CONCEPT",
        "decision_rationale": (
            "nomer provides a pluggable batch taxon-name alignment tool against GBIF, "
            "ITIS, COL, and others. The pattern (matcher registry, alignment output contract, "
            "unmatched/aligned/synonym distinction) is worth porting as concept for OC's "
            "taxon reconciliation stage. The Java CLI tool itself is not a direct dependency "
            "for a Python backend; port the alignment contract pattern instead."
        ),
        "orchid_relevance": "MEDIUM — used internally by GloBI's pipeline",
        "already_integrated": False,
        "integration_notes": "Port concept: explicit MATCHED/UNMATCHED/SYNONYM output with source backbone noted",
        "security_risk": "LOW",
        "reeval_on_release": False,
    },
    {
        "system_id": "col_checklist",
        "display_name": "Catalogue of Life (COL) Checklist API",
        "url": "https://www.catalogueoflife.org/about/colusage",
        "repositories": ["CatalogueOfLife/colplus-backend"],
        "license": "CC BY 4.0 (data)",
        "roles": ["canonical_taxon_name_resolution", "family_classification", "orchid_family_authority"],
        "reuse_decision": "FEDERATE",
        "decision_rationale": (
            "COL provides the globally accepted family-level classification for Orchidaceae. "
            "GBIF's backbone is derived from COL. Federate via API for authoritative "
            "family/genus confirmation; no source copy needed."
        ),
        "orchid_relevance": "HIGH — Orchidaceae family authority",
        "already_integrated": False,
        "integration_notes": "Use COL species ID as secondary reconciliation confirmation when GBIF match is low-confidence",
        "security_risk": "LOW",
        "reeval_on_release": False,
    },
    {
        "system_id": "inat_observations",
        "display_name": "iNaturalist Observations API",
        "url": "https://api.inaturalist.org/v1/docs/",
        "repositories": ["inaturalist/inaturalist"],
        "license": "Apache-2.0 (platform); CC BY-NC (observations, varies)",
        "roles": ["pollinator_interaction_candidates", "citizen_science_interaction_data", "media_evidence"],
        "reuse_decision": "FEDERATE",
        "decision_rationale": (
            "iNaturalist contains orchid-pollinator interaction observations with photo evidence. "
            "Federate via read-only API; output is candidate discovery context, not canonical evidence. "
            "Observation data licence varies by observer; always surface original CC licence in provenance."
        ),
        "orchid_relevance": "HIGH — citizen-science orchid observation + interaction data",
        "already_integrated": False,
        "integration_notes": "Read-only API; honour per-observation licence in provenance; treat as UNVERIFIED candidate",
        "security_risk": "LOW — public read API; account optional",
        "reeval_on_release": False,
    },
    {
        "system_id": "mycoflor",
        "display_name": "MycoFlor / Orchid Mycorrhizal Database",
        "url": "https://www.mycorrhizal-networks.org",
        "repositories": [],
        "license": "UNKNOWN — not confirmed from public documentation",
        "roles": ["mycorrhizal_interaction_candidates", "orchid_fungal_associations"],
        "reuse_decision": "CANDIDATE_UNVERIFIED",
        "decision_rationale": (
            "Specialist orchid mycorrhizal fungus association data. Licence and API availability "
            "not confirmed from public documentation. Requires further evaluation before any "
            "integration. Do not scrape; contact maintainers if integration is planned."
        ),
        "orchid_relevance": "HIGH — direct orchid mycorrhizal data",
        "already_integrated": False,
        "integration_notes": "BLOCKED on licence/API confirmation",
        "security_risk": "UNKNOWN",
        "reeval_on_release": True,
    },
    {
        "system_id": "opentraits",
        "display_name": "Open Traits Network (OTN)",
        "url": "https://opentraits.org",
        "repositories": ["open-traits-network/open-traits-network.github.io"],
        "license": "CC0 / CC BY (varies by dataset)",
        "roles": ["plant_trait_data", "trait_ontology_federation", "trait_provenance"],
        "reuse_decision": "FEDERATE",
        "decision_rationale": (
            "Open Traits provides a federation layer over multiple trait databases (TRY, LEDA, "
            "BIEN, AusTraits, etc.). Orchid-relevant morphology, habitat, and physiological "
            "trait data is available. Federate via API/data download; check per-dataset licence."
        ),
        "orchid_relevance": "MEDIUM — trait data for orchid species, not interaction-specific",
        "already_integrated": False,
        "integration_notes": "Useful for morphology and habitat trait evidence enrichment",
        "security_risk": "LOW",
        "reeval_on_release": False,
    },
    {
        "system_id": "elton",
        "display_name": "Elton (GloBI interaction dataset indexer)",
        "url": "https://github.com/globalbioticinteractions/elton",
        "repositories": ["globalbioticinteractions/elton"],
        "license": "MIT",
        "roles": ["interaction_dataset_indexing", "provider_adapter_registry", "dataset_qa"],
        "reuse_decision": "PORT_CONCEPT",
        "decision_rationale": (
            "Elton's core pattern — a registry of per-provider dataset adapters, each describing "
            "data location, format, interaction-type mapping, and QA expectations — is exactly "
            "what OC's Scientific Adapter Lab needs. Port the provider-registry-as-config pattern; "
            "do not add elton as a Java runtime dependency."
        ),
        "orchid_relevance": "MEDIUM — underpins GloBI's adapter system",
        "already_integrated": False,
        "integration_notes": "Adopt provider-config-per-dataset pattern for OC adapter registry",
        "security_risk": "LOW",
        "reeval_on_release": False,
    },
]


# ---------------------------------------------------------------------------
# Accessors
# ---------------------------------------------------------------------------


def get_candidate_matrix() -> dict[str, Any]:
    """Return the full machine-readable candidate matrix."""
    return {
        "schema_version": SCHEMA_VERSION,
        "candidate_count": len(CANDIDATE_MATRIX),
        "candidates": CANDIDATE_MATRIX,
        "graph_mutation": False,
        "automatic_publication": False,
    }


def get_candidates_by_decision(decision: str) -> list[dict[str, Any]]:
    """Return candidates filtered by reuse_decision."""
    return [c for c in CANDIDATE_MATRIX if c["reuse_decision"] == decision]


def get_integrated_candidates() -> list[dict[str, Any]]:
    """Return candidates already integrated into OC architecture."""
    return [c for c in CANDIDATE_MATRIX if c.get("already_integrated")]


def serialize_matrix_as_json(*, indent: int = 2) -> str:
    return json.dumps(get_candidate_matrix(), indent=indent, sort_keys=False)
