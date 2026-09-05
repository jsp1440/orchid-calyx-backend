"""Source discovery registry for OC-COMPLETE-004 federation/source expansion.

Systematically evaluates candidate data sources for literature, pollination,
mycorrhizal, traits, and media/herbarium domains. Each candidate record
contains all fields required by the mission acceptance criteria.

Decisions:
  KEEP    — already integrated; continue using existing adapter
  ADD     — clear path to bounded integration; child task created
  DEFER   — promising but blocked: rights unclear, API not confirmed, or
             prior work needed first
  REJECT  — not suitable; reason documented

No scraping against terms. No production KG mutation. No scientific publication.
No credentials committed. No sensitive-locality exposure.
"""

from __future__ import annotations

import json
from typing import Any

SCHEMA_VERSION = "oc-source-discovery-registry/v1"


# ---------------------------------------------------------------------------
# Source candidate records
# ---------------------------------------------------------------------------

SOURCE_CANDIDATES: list[dict[str, Any]] = [

    # -------------------------------------------------------------------------
    # LITERATURE
    # -------------------------------------------------------------------------
    {
        "source_id": "zenodo_orchid",
        "display_name": "Zenodo — orchid/botany datasets and supplementary tables",
        "domain": "literature",
        "owner": "CERN / OpenAIRE",
        "url": "https://zenodo.org",
        "api_url": "https://zenodo.org/api/records",
        "access_method": "REST API (no auth required for public records; 60 req/min public rate)",
        "license_terms": "CC BY 4.0 / CC0 / varies per deposit; always per-record. OA data freely redistributable under stated licence.",
        "data_scope": "Orchid/botany datasets, supplementary interaction tables, occurrence datasets, phylogenetic data, images, pre-publication manuscripts",
        "update_cadence": "Near-real-time (community deposits)",
        "identifiers": "Zenodo DOI (10.5281/zenodo.NNNNNNN); ORCID author; related-publication DOI",
        "overlap_with_existing": "Overlap with GloBI (GloBI deposits interaction datasets on Zenodo); GBIF (occurrence datasets); BHL (older literature may be mirrored)",
        "expected_incremental_value": "HIGH — many specialist orchid datasets not in any other federated source; supplementary tables contain interaction/trait data not otherwise machine-readable",
        "taxon_reconciliation_strategy": "Match taxon names against GBIF backbone via API; accept Zenodo-deposited GBIF taxon IDs where present",
        "provenance_contract": "Per-record DOI is citable; always surface Zenodo DOI + deposit author + licence in provenance",
        "sensitive_locality_risk": "LOW — most deposits are at species level; exact GPS coordinates should be stripped per OC locality policy if present",
        "implementation_cost": "LOW — public JSON REST API; paginated search by keyword/taxon; no authentication required",
        "decision": "ADD",
        "decision_rationale": "Best source for specialist orchid supplementary datasets not available through any other currently integrated provider. Low implementation cost.",
        "child_task_priority": "P2",
        "child_task_title": "Add Zenodo orchid-dataset federation adapter (OC-COMPLETE-004-zenodo)",
        "reeval_on_release": False,
    },
    {
        "source_id": "bhl",
        "display_name": "Biodiversity Heritage Library (BHL)",
        "domain": "literature",
        "owner": "BHL Consortium",
        "url": "https://www.biodiversitylibrary.org",
        "api_url": "https://www.biodiversitylibrary.org/api3",
        "access_method": "REST API (free API key required; no cost); full-text search by name/title/subject",
        "license_terms": "Public domain / CC0 for most scanned works; API usage terms permissive for research",
        "data_scope": "Orchid monographs, historical botany volumes, type descriptions, original species descriptions back to 18th century",
        "update_cadence": "Weekly batch",
        "identifiers": "BHLItemID, BHLPageID, DOI (some), OCLC",
        "overlap_with_existing": "Minimal — existing literature sources are primarily modern journal articles. BHL covers pre-1923 works not indexed elsewhere.",
        "expected_incremental_value": "HIGH — unique for historical nomenclatural context, type descriptions, protologues for orchid taxa",
        "taxon_reconciliation_strategy": "Name extraction from title/text; reconcile against GBIF backbone. BHL's own name-tagged pages carry scientific name spans.",
        "provenance_contract": "Surface BHLItemID + volume/page + publication title in provenance. Cite original publication, not BHL scan.",
        "sensitive_locality_risk": "NEGLIGIBLE — historical works predate precise GPS recording",
        "implementation_cost": "LOW — API key free; well-documented REST endpoints",
        "decision": "ADD",
        "decision_rationale": "Unique source for historical nomenclatural and descriptive literature. Free API key, clear terms, OA content.",
        "child_task_priority": "P3",
        "child_task_title": "Add BHL literature adapter for historical orchid literature (OC-COMPLETE-004-bhl)",
        "reeval_on_release": False,
    },
    {
        "source_id": "europepmc",
        "display_name": "Europe PMC (PubMed Central Europe)",
        "domain": "literature",
        "owner": "European Bioinformatics Institute / EMBL-EBI",
        "url": "https://europepmc.org",
        "api_url": "https://www.ebi.ac.uk/europepmc/webservices/rest",
        "access_method": "REST API (no auth required); full-text search; annotations/entity-mention API",
        "license_terms": "Open access articles: CC licence (varies). Closed-access abstracts only. API usage: free research use.",
        "data_scope": "Orchid ecology, pollination biology, mycorrhizal biology, phylogenetics papers. Full text for OA articles; abstracts for all.",
        "update_cadence": "Daily",
        "identifiers": "PMC ID, PubMed ID (PMID), DOI",
        "overlap_with_existing": "Overlaps with PubMed/MEDLINE if already integrated; distinct from BHL (modern literature only)",
        "expected_incremental_value": "HIGH — direct access to OA orchid biology literature; mentions API extracts taxon and interaction entity mentions from full text",
        "taxon_reconciliation_strategy": "Use Europe PMC entity annotation API to extract taxon mentions; reconcile against GBIF backbone by name",
        "provenance_contract": "Surface PMCID + DOI + journal + authors in provenance; distinguish OA full-text from abstract-only",
        "sensitive_locality_risk": "LOW — modern papers rarely include raw GPS in PMC metadata; strip coordinates from supplementary data if fetched",
        "implementation_cost": "LOW — free REST API; annotations endpoint reduces need for NLP on raw text",
        "decision": "ADD",
        "decision_rationale": "Best route to modern OA orchid biology literature at scale; entity annotation API enables structured taxon/interaction extraction.",
        "child_task_priority": "P2",
        "child_task_title": "Add Europe PMC literature adapter and entity annotation pipeline (OC-COMPLETE-004-europepmc)",
        "reeval_on_release": False,
    },

    # -------------------------------------------------------------------------
    # POLLINATION
    # -------------------------------------------------------------------------
    {
        "source_id": "globi_pollination",
        "display_name": "GloBI — pollination interaction records",
        "domain": "pollination",
        "owner": "Global Biotic Interactions",
        "url": "https://www.globalbioticinteractions.org",
        "api_url": "https://api.globalbioticinteractions.org",
        "access_method": "REST API and versioned stable dataset download",
        "license_terms": "CC BY / CC0 (per underlying dataset; most OA)",
        "data_scope": "Orchid-pollinator interaction records from 1000s of published datasets",
        "update_cadence": "Near-real-time (dataset submissions); versioned snapshot quarterly",
        "identifiers": "GBIF taxon ID, study DOI, GloBI interaction ID",
        "overlap_with_existing": "FULLY COVERED — runtime.interaction_harvester (live) + runtime.globi_canonical_harvester (versioned snapshot)",
        "expected_incremental_value": "N/A — already integrated",
        "taxon_reconciliation_strategy": "N/A — embedded GBIF IDs; see existing pipeline",
        "provenance_contract": "globi-canonical-dataset-review-bound-v1",
        "sensitive_locality_risk": "LOW — interaction metadata only; no precision GPS",
        "implementation_cost": "N/A — already integrated",
        "decision": "KEEP",
        "decision_rationale": "Fully integrated through existing interaction_harvester pipeline. No action needed.",
        "child_task_priority": None,
        "child_task_title": None,
        "reeval_on_release": True,
    },
    {
        "source_id": "inat_pollination",
        "display_name": "iNaturalist — orchid pollination observation API",
        "domain": "pollination",
        "owner": "iNaturalist / California Academy of Sciences",
        "url": "https://www.inaturalist.org",
        "api_url": "https://api.inaturalist.org/v1",
        "access_method": "REST API (no auth for read; rate-limited); taxon observation search",
        "license_terms": "CC BY-NC / CC BY / CC0 per observation (observer-set). Platform: Apache-2.0. Always surface per-observation licence.",
        "data_scope": "Orchid-pollinator observations with photo evidence; observer notes; geo-tagged (high locality risk)",
        "update_cadence": "Near-real-time",
        "identifiers": "iNaturalist observation ID, taxon ID (maps to GBIF), user ID",
        "overlap_with_existing": "Partial — some iNaturalist observations already flow through GloBI; direct integration adds photos and observer notes not in GloBI",
        "expected_incremental_value": "HIGH — photo-based pollinator evidence; unique observation richness for rare species",
        "taxon_reconciliation_strategy": "iNaturalist taxon IDs map to GBIF backbone; use iNat API taxon endpoint to retrieve GBIF external ID",
        "provenance_contract": "Surface iNat observation ID + observer licence + taxon authority in provenance; mark as citizen-science (UNVERIFIED, not peer-reviewed)",
        "sensitive_locality_risk": "HIGH — precise GPS for threatened orchid species; must apply locality-obscuring rules matching iNat's own obscured-coordinates policy. Strip exact_location, lat, lon from provenance. Use only the county/region level published by iNat for obscured taxa.",
        "implementation_cost": "MEDIUM — additional locality-policy enforcement layer required before any record enters OC index",
        "decision": "ADD",
        "decision_rationale": "Unique photo-evidence pollinator records; explicit locality stripping policy already built (see _strip_locality in teaching_synthesis). High scientific value.",
        "child_task_priority": "P2",
        "child_task_title": "Add iNaturalist pollination adapter with locality-obscuring enforcement (OC-COMPLETE-004-inat)",
        "reeval_on_release": False,
    },

    # -------------------------------------------------------------------------
    # MYCORRHIZAL
    # -------------------------------------------------------------------------
    {
        "source_id": "unite_its",
        "display_name": "UNITE — fungal ITS rDNA sequence database",
        "domain": "mycorrhizal",
        "owner": "UNITE Community / University of Tartu",
        "url": "https://unite.ut.ee",
        "api_url": "https://unite.ut.ee/sh_matching_api",
        "access_method": "Versioned FASTA + BIOM releases (CC BY); SH Matching REST API (free, no auth)",
        "license_terms": "CC BY 4.0 (database and sequence releases)",
        "data_scope": "Fungal ITS sequences, Species Hypotheses (SH), ecological guild annotations (mycorrhizal, saprotrophic, pathogenic)",
        "update_cadence": "Annual versioned release",
        "identifiers": "SH identifier (SH00NNNNN.07FU), INSDC accession, DOI",
        "overlap_with_existing": "Minimal — no existing mycorrhizal sequence adapter",
        "expected_incremental_value": "HIGH — orchid mycorrhizal fungal SH identifiers link molecular studies to taxa; enables sequence-level provenance for mycorrhizal associations",
        "taxon_reconciliation_strategy": "SH identifiers map to fungal species hypotheses; reconcile orchid host against GBIF backbone by name",
        "provenance_contract": "Surface UNITE release version (DOI), SH identifier, and sequence accession in provenance",
        "sensitive_locality_risk": "LOW — sequence data; collection geo-metadata may exist in INSDC records but is not the primary data product",
        "implementation_cost": "LOW for release-based; MEDIUM for SH Matching API integration",
        "decision": "ADD",
        "decision_rationale": "Unique source for molecular mycorrhizal association evidence; versioned releases with DOI ensure reproducibility. No equivalent currently integrated.",
        "child_task_priority": "P2",
        "child_task_title": "Add UNITE fungal SH adapter for orchid mycorrhizal sequence evidence (OC-COMPLETE-004-unite)",
        "reeval_on_release": True,
    },
    {
        "source_id": "mycoflor",
        "display_name": "MycoFlor / specialist orchid mycorrhizal database",
        "domain": "mycorrhizal",
        "owner": "Unknown / specialist research group",
        "url": "UNKNOWN",
        "api_url": None,
        "access_method": "UNKNOWN — no confirmed public API or download endpoint",
        "license_terms": "UNKNOWN",
        "data_scope": "Orchid mycorrhizal fungal species associations (highly relevant)",
        "update_cadence": "UNKNOWN",
        "identifiers": "UNKNOWN",
        "overlap_with_existing": "None known",
        "expected_incremental_value": "HIGH if available, but cannot be assessed without confirmed access",
        "taxon_reconciliation_strategy": "UNKNOWN",
        "provenance_contract": "UNKNOWN",
        "sensitive_locality_risk": "UNKNOWN",
        "implementation_cost": "UNKNOWN — blocked on product identification",
        "decision": "DEFER",
        "decision_rationale": "Cannot confirm product identity, public API, or licence from public documentation. Defer until maintainers confirm access path. Do not scrape.",
        "child_task_priority": None,
        "child_task_title": None,
        "reeval_on_release": True,
    },

    # -------------------------------------------------------------------------
    # TRAITS
    # -------------------------------------------------------------------------
    {
        "source_id": "austraits",
        "display_name": "AusTraits — Australian plant trait database",
        "domain": "traits",
        "owner": "Falster et al. / Australian Research Data Commons",
        "url": "https://austraits.org",
        "api_url": "https://austraits.org/downloads",
        "access_method": "Versioned release download (R package / CSV/JSON); CC BY licence; GitHub releases",
        "license_terms": "CC BY 4.0",
        "data_scope": "Australian plant traits (morphology, physiology, phenology, habitat); many orchid genera in scope (Caladenia, Pterostylis, Dendrobium, Diuris, etc.)",
        "update_cadence": "Versioned releases; roughly annual major release",
        "identifiers": "AusTraits taxon name + trait name; GBIF reconcilable by name",
        "overlap_with_existing": "Partial overlap with OpenTraits (AusTraits contributes to OTN); but direct download gives fuller data",
        "expected_incremental_value": "HIGH for Australian orchid genera; trait provenance includes per-record study citation",
        "taxon_reconciliation_strategy": "Reconcile AusTraits names against GBIF Australia backbone; AusTraits names generally follow accepted taxonomy",
        "provenance_contract": "Surface AusTraits version (DOI), trait name, per-record citation in provenance",
        "sensitive_locality_risk": "LOW — trait data; no specimen GPS",
        "implementation_cost": "LOW — static versioned release; clear schema",
        "decision": "ADD",
        "decision_rationale": "Best openly licenced source for Australian terrestrial orchid traits. Direct download path; CC BY.",
        "child_task_priority": "P3",
        "child_task_title": "Add AusTraits adapter for Australian orchid trait evidence (OC-COMPLETE-004-austraits)",
        "reeval_on_release": True,
    },
    {
        "source_id": "try_traits",
        "display_name": "TRY Plant Trait Database",
        "domain": "traits",
        "owner": "Max Planck Institute for Biogeochemistry / TRY Consortium",
        "url": "https://www.try-db.org",
        "api_url": None,
        "access_method": "Data request form; approved for research use; no open API",
        "license_terms": "CC BY-SA 4.0 pending data contributor agreements; requires submission of data request and acceptance of TRY terms",
        "data_scope": "Global plant traits; orchid-relevant coverage moderate (many taxa included but orchid family coverage uneven)",
        "update_cadence": "Annual versioned release",
        "identifiers": "TRY species code; GBIF name reconcilable",
        "overlap_with_existing": "Overlaps with AusTraits (AusTraits contributes to TRY); AusTraits is the simpler open access path",
        "expected_incremental_value": "MEDIUM — global coverage but requires formal data request process; AusTraits/OTN cover many use cases",
        "taxon_reconciliation_strategy": "TRY has its own taxon list; reconcile against GBIF backbone",
        "provenance_contract": "Surface TRY dataset version + contributor dataset DOI per record",
        "sensitive_locality_risk": "LOW",
        "implementation_cost": "MEDIUM — formal request process before access; then static release processing",
        "decision": "DEFER",
        "decision_rationale": "Formal data request required; AusTraits and OpenTraits cover most use cases with simpler access. Re-evaluate if global trait coverage beyond AusTraits becomes critical.",
        "child_task_priority": None,
        "child_task_title": None,
        "reeval_on_release": True,
    },

    # -------------------------------------------------------------------------
    # MEDIA / HERBARIUM
    # -------------------------------------------------------------------------
    {
        "source_id": "idigbio",
        "display_name": "iDigBio — Integrated Digitized Biocollections",
        "domain": "media",
        "owner": "University of Florida / NSF",
        "url": "https://www.idigbio.org",
        "api_url": "https://search.idigbio.org/v2",
        "access_method": "REST API (no auth required); specimen + media search by taxon, institution, collection",
        "license_terms": "CC0 (metadata); media licences vary per institution (CC BY / public domain most common for herbarium images)",
        "data_scope": "US-based herbarium specimens for orchid taxa; images, label data, collector info, collection date, geo-data",
        "update_cadence": "Near-real-time aggregation from member institutions",
        "identifiers": "iDigBio UUID, institutionCode + catalogNumber, GBIF occurrence ID (many records cross-linked)",
        "overlap_with_existing": "Partial overlap with GBIF occurrence data; iDigBio provides higher-resolution images and more complete US specimen label data",
        "expected_incremental_value": "HIGH — specimen images for morphological reference; label data for historical distribution",
        "taxon_reconciliation_strategy": "iDigBio taxon names reconcile via GBIF; iDigBio API accepts dwc:scientificName queries",
        "provenance_contract": "Surface iDigBio UUID + institutionCode + catalogNumber + image URL + media licence in provenance",
        "sensitive_locality_risk": "MEDIUM — some specimens carry exact GPS; apply locality stripping for threatened orchid taxa. iDigBio itself redacts coordinates for COSEWIC/CITES taxa.",
        "implementation_cost": "LOW — open REST API; no auth; well-documented",
        "decision": "ADD",
        "decision_rationale": "Unique US herbarium specimen image source; complements GBIF occurrence data with higher-resolution label and image data. Clear open API.",
        "child_task_priority": "P3",
        "child_task_title": "Add iDigBio herbarium specimen + media adapter (OC-COMPLETE-004-idigbio)",
        "reeval_on_release": False,
    },
    {
        "source_id": "pow_kew",
        "display_name": "Plants of the World Online (POWO) — Kew Royal Botanic Gardens",
        "domain": "media",
        "owner": "Royal Botanic Gardens, Kew",
        "url": "https://powo.science.kew.org",
        "api_url": "https://powo.science.kew.org/api/2",
        "access_method": "REST API (no auth required for most endpoints); taxon lookup, synonym list, distribution, images",
        "license_terms": "CC BY 4.0 (text and some images); some image licences vary. API terms permit research use.",
        "data_scope": "Complete Orchidaceae taxonomy from World Checklist of Selected Plant Families (WCSP); accepted names, synonyms, distributions, select images",
        "update_cadence": "Regular (Kew editorial updates)",
        "identifiers": "POWO plant ID (e.g. urn:lsid:ipni.org:names:NNNNN-1), IPNI ID, GBIF cross-linkable",
        "overlap_with_existing": "Partial with GBIF backbone (Kew WCSP is a source for GBIF); POWO provides authoritative Orchidaceae family treatments",
        "expected_incremental_value": "HIGH — authoritative orchid family taxonomy; synonym resolution; native distribution polygons not otherwise integrated",
        "taxon_reconciliation_strategy": "POWO ID → IPNI ID → GBIF backbone cross-linking; POWO is the authority source for Orchidaceae family",
        "provenance_contract": "Surface POWO plant ID + Kew attribution + WCSP version in provenance",
        "sensitive_locality_risk": "LOW — distribution data at country/region level; no precise GPS in POWO API",
        "implementation_cost": "LOW — open REST API; no auth",
        "decision": "ADD",
        "decision_rationale": "Authoritative Orchidaceae taxonomy, synonym handling, and distribution data from Kew. Low cost, clear provenance, high value for taxon reconciliation.",
        "child_task_priority": "P2",
        "child_task_title": "Add Kew POWO taxonomy and distribution adapter (OC-COMPLETE-004-powo)",
        "reeval_on_release": True,
    },
    {
        "source_id": "gbif_occurrence",
        "display_name": "GBIF Occurrence API",
        "domain": "media",
        "owner": "Global Biodiversity Information Facility",
        "url": "https://www.gbif.org",
        "api_url": "https://api.gbif.org/v1/occurrence/search",
        "access_method": "REST API (no auth for public data; account for download); species/occurrence search",
        "license_terms": "CC0 / CC BY / CC BY-NC (per dataset; always surface dataset licence)",
        "data_scope": "Orchid occurrence records from 1000s of institutions; geo-tagged specimens, observations, images",
        "update_cadence": "Near-real-time (partner institution sync)",
        "identifiers": "GBIF occurrence key, dataset key, taxon key (=backbone ID)",
        "overlap_with_existing": "GloBI uses GBIF IDs for taxon reconciliation; occurrence data itself not yet integrated",
        "expected_incremental_value": "HIGH — global occurrence coverage; distribution evidence; links to specimen images; cross-referenced with existing taxon IDs",
        "taxon_reconciliation_strategy": "GBIF taxon key is the canonical OC taxon ID; occurrence records inherit the same ID directly",
        "provenance_contract": "Surface GBIF dataset key + occurrence key + dataset DOI + publishing institution + record licence",
        "sensitive_locality_risk": "HIGH — GBIF automatically redacts coordinates for threatened/sensitive taxa; OC must respect GBIF's own redaction and apply additional locality stripping for CITES-listed orchid taxa",
        "implementation_cost": "LOW — world-class REST API; GBIF taxon keys already used in existing pipeline",
        "decision": "ADD",
        "decision_rationale": "Natural complement to existing GBIF taxon ID usage; occurrence records provide distribution evidence. Locality policy already established in OC.",
        "child_task_priority": "P2",
        "child_task_title": "Add GBIF occurrence adapter for orchid distribution and specimen evidence (OC-COMPLETE-004-gbif-occurrence)",
        "reeval_on_release": False,
    },
]


# ---------------------------------------------------------------------------
# Accessors and report builders
# ---------------------------------------------------------------------------


def get_source_registry() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "source_count": len(SOURCE_CANDIDATES),
        "candidates": SOURCE_CANDIDATES,
        "graph_mutation": False,
        "automatic_publication": False,
    }


def get_sources_by_decision(decision: str) -> list[dict[str, Any]]:
    return [s for s in SOURCE_CANDIDATES if s["decision"] == decision]


def get_add_candidates() -> list[dict[str, Any]]:
    return get_sources_by_decision("ADD")


def get_child_task_specs() -> list[dict[str, Any]]:
    """Return child implementation task specs for all ADD-decision candidates."""
    return [
        {
            "source_id": s["source_id"],
            "title": s["child_task_title"],
            "priority": s["child_task_priority"],
            "domain": s["domain"],
            "decision_rationale": s["decision_rationale"],
        }
        for s in SOURCE_CANDIDATES
        if s["decision"] == "ADD" and s.get("child_task_title")
    ]


def get_sources_by_domain(domain: str) -> list[dict[str, Any]]:
    return [s for s in SOURCE_CANDIDATES if s["domain"] == domain]


def serialize_registry_as_json(*, indent: int = 2) -> str:
    return json.dumps(get_source_registry(), indent=indent, sort_keys=False)
