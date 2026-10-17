"""External scientific source registry integration for the Orchid Continuum.

Integrates the 25-source external registry artifact
(``orchid_continuum_source_registry.json`` / ``.csv``, version 1.0.0,
generated 2026-10-10) into the *existing* scientific source infrastructure:

  - Provider definitions: ``app/scientific_adapter_lab/source_discovery_registry.py``
    (``oc-source-discovery-registry/v1``). This module does NOT create a
    duplicate registry; it reconciles the external artifact's source IDs
    against ``SOURCE_CANDIDATES`` and reuses the existing accessors.
  - Ingestion adapters: ``harvesters/`` (BaseHarvester implementations) and
    ``runtime/interaction_harvester.py``, ``runtime/globi_canonical_harvester.py``,
    ``runtime/literature_harvester.py``. Reconciliation entries point at these
    existing adapters rather than defining new ones.
  - Licensing safeguards: fail-closed ingestion gating consistent with
    ``app/source_federation/inventory.py`` (RightsState open/restricted/unknown;
    restricted or unknown rights block admission).

Governance invariants (mirrors the mission constraints and the existing
registry contract):

  - ``graph_mutation: False`` — this integration mutates no knowledge graph.
  - ``automatic_publication: False`` — nothing is published automatically.
  - The World Plants (Dr. Michael Hassler) taxonomic backbone is preserved.
    WCVP, POWO, IPNI, WFO, COL and NCBI are authority *mappings* only
    (BUILD-065 owner decision); they never replace the canonical backbone.
  - Automated ingestion is blocked (fail-closed) for any source whose
    licensing is uncertain — including Species+ and all partially verified
    sources — until appropriate permissions are established.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

INTEGRATION_SCHEMA_VERSION = "oc-external-source-registry-integration/v1"
REGISTRY_ARTIFACT_VERSION = "1.0.0"
REGISTRY_ARTIFACT_GENERATED = "2026-10-10"

_DATA_DIR = Path(__file__).resolve().parent / "data"
DEFAULT_JSON_PATH = _DATA_DIR / "orchid_continuum_source_registry.json"
DEFAULT_CSV_PATH = _DATA_DIR / "orchid_continuum_source_registry.csv"

# ---------------------------------------------------------------------------
# Module bindings: the five consuming modules and their existing calyx code.
# ---------------------------------------------------------------------------

MODULE_KEYS = ("lexicon", "glossary", "literature", "dossiers", "matrix")

MODULE_BINDINGS: dict[str, dict[str, str]] = {
    "lexicon": {
        "label": "Lexicon",
        "module_path": "app/lexicon",
    },
    "glossary": {
        "label": "Illustrated Glossary",
        "module_path": "app/scientific_adapter_lab/glossary_intake_bridge.py",
    },
    "literature": {
        "label": "Literature Extraction",
        "module_path": "app/literature_extraction",
    },
    "dossiers": {
        "label": "Species Dossiers",
        "module_path": "app/species_dossier",
    },
    "matrix": {
        "label": "Matrix",
        "module_path": "runtime/matrix_identification.py",
    },
}

# ---------------------------------------------------------------------------
# Verification status handling (codes defined by the artifact itself).
# ---------------------------------------------------------------------------

VERIFIED_STATUSES = frozenset({"verified_prior", "verified_new"})
UNVERIFIED_STATUSES = frozenset({"partially_verified", "needs_manual_review"})
KNOWN_STATUSES = VERIFIED_STATUSES | UNVERIFIED_STATUSES

# ---------------------------------------------------------------------------
# Canonical taxonomic backbone preservation (BUILD-065 owner decision).
# The canonical authority is World Plants; other taxonomic sources are
# authority *mappings* only and must never be treated as a competing backbone.
# ---------------------------------------------------------------------------

CANONICAL_TAXONOMIC_AUTHORITY = "world_plants"
CANONICAL_TAXONOMIC_AUTHORITY_LABEL = "World Plants (Dr. Michael Hassler)"
CANONICAL_TAXONOMY_IMPL = "runtime/knowledge_graph/canonical_taxonomy.py"

# Authority labels accepted as mappings. GBIF/POWO/IPNI/WFO/NCBI are the
# mapping authorities already enumerated in canonical_taxonomy.AUTHORITY_SOURCES;
# WCVP and COL are additional mapping labels introduced by this artifact.
AUTHORITY_MAPPING_LABELS = frozenset(
    {"GBIF", "POWO", "IPNI", "WFO", "NCBI", "WCVP", "COL"}
)


class BackboneViolationError(RuntimeError):
    """Raised when a source would displace the World Plants backbone."""


# ---------------------------------------------------------------------------
# Ingestion gating (fail-closed licensing safeguards).
# ---------------------------------------------------------------------------


class IngestionGate(StrEnum):
    """Automated-ingestion gate for a registry source.

    ELIGIBLE     — verified status and no per-record/uncertain licensing
                   markers; automated ingestion may proceed under the
                   existing reviewed adapter scope.
    CONDITIONAL  — licensing is granted per record / per dataset / per file
                   (or similarly granular); automated ingestion is NOT
                   cleared, but the source remains usable through existing
                   adapters that surface per-record license and attribution
                   fields, under current reviewed scope.
    BLOCKED      — verification incomplete or licensing uncertain/restricted;
                   automated ingestion is blocked until permissions are
                   established.
    """

    ELIGIBLE = "eligible"
    CONDITIONAL = "conditional"
    BLOCKED = "blocked"


_LICENSE_SCAN_FIELDS = (
    "data_license",
    "media_license",
    "commercial_use",
    "ai_training_restriction",
    "attribution_requirement",
)

# Markers that indicate licensing is uncertain or hard-restricted. Any hit
# blocks automated ingestion outright (fail closed).
_HARD_RESTRICTION_MARKERS = (
    "strictly forbidden",
    "not retrievable",
    "unverified",
    "no cc license",
    "restricted",
)

# Markers that indicate licensing is decided per record / dataset / file and
# therefore cannot be cleared wholesale for automated ingestion.
_PER_RECORD_MARKERS = (
    "per-record",
    "per-dataset",
    "per-file",
    "per-item",
    "per article",
    "per contributor",
    "per-media",
    "per-recordset",
    "per underlying source",
    "underlying records per source",
    "per source",
    "mixed",
    "varies",
    "may be copyrighted",
    "except",
)


def evaluate_ingestion_gate(source: dict[str, Any]) -> IngestionGate:
    """Derive the automated-ingestion gate for one registry source.

    Fail-closed: unrecognized verification statuses, unretrievable or
    restricted terms, and uncertain licensing all yield BLOCKED. Per-record
    licensing yields CONDITIONAL. Only verified sources with cleanly stated
    open licensing are ELIGIBLE for automated ingestion.
    """

    status = str(source.get("verification_status", "")).strip()
    if status not in VERIFIED_STATUSES:
        # partially_verified, needs_manual_review, or anything unrecognized:
        # licensing detail is by definition not fully established.
        return IngestionGate.BLOCKED

    haystack = " \n ".join(
        str(source.get(f, "")) for f in _LICENSE_SCAN_FIELDS
    ).lower()

    if any(marker in haystack for marker in _HARD_RESTRICTION_MARKERS):
        return IngestionGate.BLOCKED
    if any(marker in haystack for marker in _PER_RECORD_MARKERS):
        return IngestionGate.CONDITIONAL
    return IngestionGate.ELIGIBLE


def gate_rationale(source: dict[str, Any]) -> str:
    """Human-readable explanation of the gate decision."""

    gate = evaluate_ingestion_gate(source)
    status = str(source.get("verification_status", "")).strip()
    if gate is IngestionGate.BLOCKED:
        if status in UNVERIFIED_STATUSES:
            return (
                f"verification_status={status}: licensing/permission detail "
                "not fully established; automated ingestion blocked until "
                "permissions are confirmed"
            )
        if status not in KNOWN_STATUSES:
            return f"unrecognized verification_status={status!r}; fail closed"
        return (
            "licensing fields contain restricted or uncertain terms; "
            "automated ingestion blocked"
        )
    if gate is IngestionGate.CONDITIONAL:
        return (
            "per-record/per-dataset licensing; not cleared for automated "
            "ingestion, usable via existing adapters that surface per-record "
            "license and attribution fields under reviewed scope"
        )
    return "verified status and cleanly stated open licensing"

# ---------------------------------------------------------------------------
# Source-ID reconciliation against the existing provider registry and
# ingestion adapters. ``existing_candidate_id`` values are source_ids from
# app/scientific_adapter_lab/source_discovery_registry.py SOURCE_CANDIDATES.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReconciliationEntry:
    """How one external-registry source maps onto existing infrastructure."""

    source_id: str
    existing_candidate_id: str | None = None
    existing_adapter_paths: tuple[str, ...] = ()
    # "authority_mapping" for taxonomic authorities that map onto the World
    # Plants backbone; None otherwise. Never "canonical_backbone".
    taxonomy_role: str | None = None
    authority_label: str | None = None
    notes: str = ""


SOURCE_ID_RECONCILIATION: dict[str, ReconciliationEntry] = {
    "inat": ReconciliationEntry(
        source_id="inat",
        existing_candidate_id="inat_pollination",
        existing_adapter_paths=("harvesters/inat.py",),
        notes=(
            "Existing iNaturalist harvester surfaces per-photo license_code "
            "and photographer attribution per record."
        ),
    ),
    "gbif": ReconciliationEntry(
        source_id="gbif",
        existing_candidate_id="gbif_occurrence",
        existing_adapter_paths=(
            "harvesters/gbif_api.py",
            "harvesters/gbif_global_api.py",
        ),
        notes="Existing GBIF harvesters carry per-record license fields.",
    ),
    "bhl": ReconciliationEntry(
        source_id="bhl",
        existing_candidate_id="bhl",
        existing_adapter_paths=(
            "runtime/literature_harvester.py",
            "app/harvest/plugins/bhl/client.py",
        ),
    ),
    "idigbio": ReconciliationEntry(
        source_id="idigbio",
        existing_candidate_id="idigbio",
    ),
    "globi": ReconciliationEntry(
        source_id="globi",
        existing_candidate_id="globi_pollination",
        existing_adapter_paths=(
            "runtime/interaction_harvester.py",
            "runtime/globi_canonical_harvester.py",
        ),
        notes=(
            "GloBI is KEEP in the existing registry; harvesters return "
            "review_required=True with no automatic publication."
        ),
    ),
    "eol_traitbank": ReconciliationEntry(
        source_id="eol_traitbank",
        existing_adapter_paths=("harvesters/traitbank.py",),
    ),
    "unite": ReconciliationEntry(
        source_id="unite",
        existing_candidate_id="unite_its",
    ),
    "powo": ReconciliationEntry(
        source_id="powo",
        existing_candidate_id="pow_kew",
        taxonomy_role="authority_mapping",
        authority_label="POWO",
    ),
    "wcvp": ReconciliationEntry(
        source_id="wcvp",
        taxonomy_role="authority_mapping",
        authority_label="WCVP",
        notes=(
            "WCVP is an authority mapping onto the World Plants backbone, "
            "never a replacement for it."
        ),
    ),
    "ipni": ReconciliationEntry(
        source_id="ipni",
        taxonomy_role="authority_mapping",
        authority_label="IPNI",
    ),
    "wfo": ReconciliationEntry(
        source_id="wfo",
        taxonomy_role="authority_mapping",
        authority_label="WFO",
    ),
    "col": ReconciliationEntry(
        source_id="col",
        taxonomy_role="authority_mapping",
        authority_label="COL",
    ),
    "ncbi_taxonomy": ReconciliationEntry(
        source_id="ncbi_taxonomy",
        taxonomy_role="authority_mapping",
        authority_label="NCBI",
    ),
    "iucn": ReconciliationEntry(
        source_id="iucn",
        notes=(
            "IUCN Terms of Use; no CC license; commercial use strictly "
            "forbidden. Blocked pending explicit permission."
        ),
    ),
    "speciesplus": ReconciliationEntry(
        source_id="speciesplus",
        notes=(
            "Terms of use not retrievable at verification time; blocked "
            "pending manual review and established permissions."
        ),
    ),
    "plazi": ReconciliationEntry(source_id="plazi"),
    "openalex": ReconciliationEntry(source_id="openalex"),
    "crossref": ReconciliationEntry(
        source_id="crossref",
        existing_adapter_paths=("runtime/literature_harvester.py",),
    ),
    "europepmc": ReconciliationEntry(
        source_id="europepmc",
        existing_candidate_id="europepmc",
        existing_adapter_paths=("runtime/literature_harvester.py",),
    ),
    "gnverifier": ReconciliationEntry(source_id="gnverifier"),
    "plant_ontology": ReconciliationEntry(source_id="plant_ontology"),
    "darwin_core": ReconciliationEntry(source_id="darwin_core"),
    "wikidata": ReconciliationEntry(source_id="wikidata"),
    "wikimedia_commons": ReconciliationEntry(source_id="wikimedia_commons"),
    "try": ReconciliationEntry(
        source_id="try",
        existing_candidate_id="try_traits",
    ),
}

# ---------------------------------------------------------------------------
# Artifact loading and validation.
# ---------------------------------------------------------------------------

REQUIRED_SOURCE_FIELDS = frozenset(
    {
        "source_id",
        "name",
        "source_type",
        "modules",
        "primary_role",
        "base_url",
        "api_endpoint",
        "auth",
        "cost",
        "rate_limits",
        "bulk_access",
        "data_license",
        "media_license",
        "commercial_use",
        "ai_training_restriction",
        "attribution_requirement",
        "recommended_citation",
        "verification_status",
        "verified_date",
        "evidence_url",
        "provenance",
        "notes",
    }
)

REQUIRED_TOP_LEVEL_KEYS = frozenset(
    {
        "registry",
        "version",
        "generated",
        "modules",
        "verification_status_codes",
        "module_index",
        "sources",
    }
)


def load_bundled_registry(path: str | Path | None = None) -> dict[str, Any]:
    """Load the bundled registry artifact JSON."""

    artifact = Path(path) if path is not None else DEFAULT_JSON_PATH
    with artifact.open(encoding="utf-8") as fh:
        return json.load(fh)


def load_bundled_registry_csv(path: str | Path | None = None) -> list[dict[str, str]]:
    """Load the flattened CSV export of the registry artifact."""

    artifact = Path(path) if path is not None else DEFAULT_CSV_PATH
    with artifact.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def validate_registry_payload(payload: dict[str, Any]) -> list[str]:
    """Validate a registry payload; returns a list of problems (empty = valid)."""

    problems: list[str] = []

    missing_top = REQUIRED_TOP_LEVEL_KEYS - set(payload)
    if missing_top:
        problems.append(f"missing top-level keys: {sorted(missing_top)}")
        return problems  # cannot meaningfully validate further

    if payload.get("version") != REGISTRY_ARTIFACT_VERSION:
        problems.append(
            f"unexpected artifact version {payload.get('version')!r}; "
            f"expected {REGISTRY_ARTIFACT_VERSION!r}"
        )

    modules_declared = payload.get("modules", {})
    if set(modules_declared) != set(MODULE_KEYS):
        problems.append(
            f"modules keys {sorted(modules_declared)} != {sorted(MODULE_KEYS)}"
        )

    status_codes = payload.get("verification_status_codes", {})
    if set(status_codes) != KNOWN_STATUSES:
        problems.append(
            f"verification_status_codes {sorted(status_codes)} != "
            f"{sorted(KNOWN_STATUSES)}"
        )

    sources = payload.get("sources", [])
    seen_ids: set[str] = set()
    for idx, source in enumerate(sources):
        sid = source.get("source_id", f"<index {idx}>")
        missing = REQUIRED_SOURCE_FIELDS - set(source)
        if missing:
            problems.append(f"source {sid}: missing fields {sorted(missing)}")
        if sid in seen_ids:
            problems.append(f"duplicate source_id {sid!r}")
        seen_ids.add(sid)
        status = source.get("verification_status")
        if status not in KNOWN_STATUSES:
            problems.append(f"source {sid}: unknown verification_status {status!r}")
        mods = source.get("modules", [])
        if not isinstance(mods, list) or not set(mods) <= set(MODULE_KEYS):
            problems.append(f"source {sid}: invalid modules {mods!r}")

    # module_index must be bidirectionally consistent with source.modules
    module_index = payload.get("module_index", {})
    if set(module_index) != set(MODULE_KEYS):
        problems.append(
            f"module_index keys {sorted(module_index)} != {sorted(MODULE_KEYS)}"
        )
    else:
        for mod_key in MODULE_KEYS:
            indexed = set(module_index.get(mod_key, []))
            declared = {
                s.get("source_id")
                for s in sources
                if mod_key in (s.get("modules") or [])
            }
            if indexed != declared:
                problems.append(
                    f"module_index[{mod_key!r}] inconsistent with source modules: "
                    f"index-only {sorted(indexed - declared)}, "
                    f"source-only {sorted(declared - indexed)}"
                )

    return problems

# ---------------------------------------------------------------------------
# Reconciliation, module lookup, backbone preservation, and reporting.
# ---------------------------------------------------------------------------


def reconcile_sources(
    payload: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Reconcile every artifact source against existing infrastructure.

    Returns one record per source with its ingestion gate, existing provider
    candidate mapping (if any), existing adapter paths (if any), taxonomy
    role, and whether automated ingestion is cleared. Fail-closed: a source
    whose ID has no reconciliation entry is treated as unrecognized and
    blocked regardless of its other fields.
    """

    if payload is None:
        payload = load_bundled_registry()

    records: list[dict[str, Any]] = []
    for source in payload.get("sources", []):
        sid = source.get("source_id", "")
        entry = SOURCE_ID_RECONCILIATION.get(sid)
        gate = evaluate_ingestion_gate(source)
        rationale = gate_rationale(source)
        if entry is None:
            gate = IngestionGate.BLOCKED
            rationale = f"unrecognized source_id {sid!r}; fail closed"

        records.append(
            {
                "source_id": sid,
                "name": source.get("name"),
                "modules": list(source.get("modules", [])),
                "verification_status": source.get("verification_status"),
                "ingestion_gate": gate.value,
                "automated_ingestion_cleared": gate is IngestionGate.ELIGIBLE,
                "gate_rationale": rationale,
                "existing_candidate_id": entry.existing_candidate_id if entry else None,
                "existing_adapter_paths": list(entry.existing_adapter_paths) if entry else [],
                # Existing adapters continue operating under their current
                # reviewed scope; the gate governs *new automated* ingestion.
                "existing_adapter_continuity": bool(entry and entry.existing_adapter_paths),
                "taxonomy_role": entry.taxonomy_role if entry else None,
                "authority_label": entry.authority_label if entry else None,
                "attribution_requirement": source.get("attribution_requirement"),
                "recommended_citation": source.get("recommended_citation"),
                "evidence_url": source.get("evidence_url"),
                "provenance": source.get("provenance"),
            }
        )
    return records


def sources_for_module(
    module_key: str,
    payload: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Module-to-source lookup for one of the five consuming modules.

    Returns reconciled records (including gate status) for all sources that
    feed the given module. Blocked sources remain visible so the module can
    surface them as pending-permission rather than silently dropping them.
    """

    if module_key not in MODULE_KEYS:
        raise KeyError(
            f"unknown module {module_key!r}; expected one of {sorted(MODULE_KEYS)}"
        )
    return [r for r in reconcile_sources(payload) if module_key in r["modules"]]


def assert_backbone_preserved(payload: dict[str, Any] | None = None) -> None:
    """Verify no source displaces the World Plants taxonomic backbone.

    Raises BackboneViolationError if any source claims a canonical-backbone
    taxonomy role, carries an unrecognized authority label, or if the
    canonical authority constant has been changed away from World Plants.
    """

    if CANONICAL_TAXONOMIC_AUTHORITY != "world_plants":
        raise BackboneViolationError(
            f"canonical taxonomic authority is {CANONICAL_TAXONOMIC_AUTHORITY!r}; "
            "must remain 'world_plants' (World Plants, Dr. Michael Hassler)"
        )

    if payload is None:
        payload = load_bundled_registry()

    for source in payload.get("sources", []):
        sid = source.get("source_id", "")
        entry = SOURCE_ID_RECONCILIATION.get(sid)
        if entry is None:
            continue
        if entry.taxonomy_role == "canonical_backbone":
            raise BackboneViolationError(
                f"source {sid!r} declares taxonomy_role='canonical_backbone'; "
                "the canonical backbone is World Plants and cannot be replaced"
            )
        if entry.taxonomy_role == "authority_mapping" and (
            entry.authority_label not in AUTHORITY_MAPPING_LABELS
        ):
            raise BackboneViolationError(
                f"source {sid!r} has unrecognized authority label "
                f"{entry.authority_label!r}"
            )


def project_new_candidates(
    payload: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Project not-yet-registered sources into existing-registry shape.

    Sources that already map to an existing SOURCE_CANDIDATES entry are
    excluded (the existing candidate definition is reused, not duplicated).
    The remainder are projected with the existing registry's decision
    vocabulary: ELIGIBLE sources become ADD candidates at bounded priority;
    CONDITIONAL and BLOCKED sources become DEFER with their blockers
    recorded. No projection ever enables graph mutation or automatic
    publication.
    """

    if payload is None:
        payload = load_bundled_registry()

    projections: list[dict[str, Any]] = []
    for record in reconcile_sources(payload):
        if record["existing_candidate_id"] is not None:
            continue
        gate = IngestionGate(record["ingestion_gate"])
        if gate is IngestionGate.ELIGIBLE:
            decision = "ADD"
            priority = "P3"
            blockers: list[str] = []
        else:
            decision = "DEFER"
            priority = None
            blockers = [record["gate_rationale"]]
        projections.append(
            {
                "source_id": record["source_id"],
                "decision": decision,
                "priority": priority,
                "admission_blockers": blockers,
                "modules": record["modules"],
                "taxonomy_role": record["taxonomy_role"],
                "attribution_requirement": record["attribution_requirement"],
                "graph_mutation": False,
                "automatic_publication": False,
            }
        )
    return projections


def reconciliation_report(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Summarize the integration for review: gates, coverage, safeguards."""

    if payload is None:
        payload = load_bundled_registry()

    records = reconcile_sources(payload)
    by_gate: dict[str, list[str]] = {g.value: [] for g in IngestionGate}
    by_status: dict[str, int] = {}
    for record in records:
        by_gate[record["ingestion_gate"]].append(record["source_id"])
        status = record["verification_status"]
        by_status[status] = by_status.get(status, 0) + 1

    module_coverage = {
        key: {
            "label": MODULE_BINDINGS[key]["label"],
            "module_path": MODULE_BINDINGS[key]["module_path"],
            "sources": [r["source_id"] for r in records if key in r["modules"]],
            "blocked_sources": [
                r["source_id"]
                for r in records
                if key in r["modules"]
                and r["ingestion_gate"] == IngestionGate.BLOCKED.value
            ],
        }
        for key in MODULE_KEYS
    }

    return {
        "schema": INTEGRATION_SCHEMA_VERSION,
        "artifact_version": payload.get("version"),
        "artifact_generated": payload.get("generated"),
        "total_sources": len(records),
        "gates": {k: sorted(v) for k, v in by_gate.items()},
        "verification_statuses": by_status,
        "module_coverage": module_coverage,
        "canonical_taxonomic_authority": CANONICAL_TAXONOMIC_AUTHORITY,
        "canonical_taxonomic_authority_label": CANONICAL_TAXONOMIC_AUTHORITY_LABEL,
        "canonical_taxonomy_impl": CANONICAL_TAXONOMY_IMPL,
        "graph_mutation": False,
        "automatic_publication": False,
    }
