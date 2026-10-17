"""Tests for the external source registry integration.

Covers:
  1. Registry artifact validation (JSON schema, CSV/JSON parity).
  2. Source-ID reconciliation against the existing provider registry and
     existing ingestion adapters.
  3. License restrictions / fail-closed ingestion gating.
  4. Module-to-source lookup for Lexicon, Illustrated Glossary, Literature
     Extraction, Species Dossiers, and Matrix.
  5. World Plants taxonomic backbone preservation.
  6. Compatibility with existing ingestion interfaces (BaseHarvester,
     existing harvester entry points and license/attribution surfacing).

Offline-safe: no network, no database. Harvesters that import psycopg2 at
module load are checked via static AST parsing instead of import.
"""

from __future__ import annotations

import ast
import csv
import importlib.util
import json
from pathlib import Path

import pytest

from app.scientific_adapter_lab import external_source_registry as esr
from app.scientific_adapter_lab.source_discovery_registry import (
    SOURCE_CANDIDATES,
    get_source_registry,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

EXPECTED_SOURCE_COUNT = 25
EXPECTED_ELIGIBLE = {
    "unite",
    "wcvp",
    "ipni",
    "col",
    "ncbi_taxonomy",
    "openalex",
    "plant_ontology",
    "darwin_core",
    "wikidata",
}
EXPECTED_CONDITIONAL = {
    "inat",
    "gbif",
    "bhl",
    "idigbio",
    "globi",
    "eol_traitbank",
    "powo",
    "wfo",
    "crossref",
    "wikimedia_commons",
}
EXPECTED_BLOCKED = {
    "iucn",
    "speciesplus",
    "plazi",
    "europepmc",
    "gnverifier",
    "try",
}


@pytest.fixture(scope="module")
def payload():
    return esr.load_bundled_registry()


@pytest.fixture(scope="module")
def reconciled(payload):
    return {r["source_id"]: r for r in esr.reconcile_sources(payload)}


def _load_module_from_path(module_name: str, path: Path):
    """Load a module directly from a file path, bypassing package __init__."""

    import sys

    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    # Register before exec so dataclass processing can resolve the module.
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# 1. Registry validation
# ---------------------------------------------------------------------------


class TestRegistryValidation:
    def test_bundled_artifact_validates_clean(self, payload):
        assert esr.validate_registry_payload(payload) == []

    def test_artifact_has_25_sources(self, payload):
        assert len(payload["sources"]) == EXPECTED_SOURCE_COUNT

    def test_artifact_version_pinned(self, payload):
        assert payload["version"] == esr.REGISTRY_ARTIFACT_VERSION
        assert payload["generated"] == esr.REGISTRY_ARTIFACT_GENERATED

    def test_every_source_has_required_fields(self, payload):
        for source in payload["sources"]:
            assert esr.REQUIRED_SOURCE_FIELDS <= set(source), source["source_id"]

    def test_source_ids_unique(self, payload):
        ids = [s["source_id"] for s in payload["sources"]]
        assert len(ids) == len(set(ids))

    def test_verification_status_codes_match_known_set(self, payload):
        assert set(payload["verification_status_codes"]) == esr.KNOWN_STATUSES

    def test_module_index_bidirectionally_consistent(self, payload):
        for key in esr.MODULE_KEYS:
            indexed = set(payload["module_index"][key])
            declared = {
                s["source_id"] for s in payload["sources"] if key in s["modules"]
            }
            assert indexed == declared, key

    def test_missing_top_level_key_detected(self, payload):
        broken = {k: v for k, v in payload.items() if k != "sources"}
        problems = esr.validate_registry_payload(broken)
        assert any("sources" in p for p in problems)

    def test_unknown_verification_status_detected(self, payload):
        broken = json.loads(json.dumps(payload))
        broken["sources"][0]["verification_status"] = "totally_legit"
        problems = esr.validate_registry_payload(broken)
        assert any("verification_status" in p for p in problems)

    def test_module_index_inconsistency_detected(self, payload):
        broken = json.loads(json.dumps(payload))
        broken["module_index"]["matrix"] = ["gbif"]
        problems = esr.validate_registry_payload(broken)
        assert any("module_index" in p for p in problems)

    def test_csv_export_matches_json_sources(self, payload):
        rows = esr.load_bundled_registry_csv()
        assert len(rows) == EXPECTED_SOURCE_COUNT
        csv_ids = {row["source_id"] for row in rows}
        json_ids = {s["source_id"] for s in payload["sources"]}
        assert csv_ids == json_ids
        by_id = {s["source_id"]: s for s in payload["sources"]}
        for row in rows:
            source = by_id[row["source_id"]]
            assert row["verification_status"] == source["verification_status"]
            assert row["data_license"] == source["data_license"]
            assert row["attribution_requirement"] == source["attribution_requirement"]


# ---------------------------------------------------------------------------
# 2. Source-ID reconciliation
# ---------------------------------------------------------------------------


class TestSourceReconciliation:
    def test_all_artifact_sources_have_reconciliation_entries(self, payload):
        for source in payload["sources"]:
            assert source["source_id"] in esr.SOURCE_ID_RECONCILIATION

    def test_existing_candidate_ids_exist_in_provider_registry(self):
        existing_ids = {c["source_id"] for c in SOURCE_CANDIDATES}
        for entry in esr.SOURCE_ID_RECONCILIATION.values():
            if entry.existing_candidate_id is not None:
                assert entry.existing_candidate_id in existing_ids, entry

    def test_expected_existing_provider_mappings(self, reconciled):
        expected = {
            "inat": "inat_pollination",
            "gbif": "gbif_occurrence",
            "bhl": "bhl",
            "idigbio": "idigbio",
            "globi": "globi_pollination",
            "unite": "unite_its",
            "try": "try_traits",
            "powo": "pow_kew",
            "europepmc": "europepmc",
        }
        for sid, candidate_id in expected.items():
            assert reconciled[sid]["existing_candidate_id"] == candidate_id, sid

    def test_no_duplicate_registry_created(self):
        # The integration reuses the existing provider registry rather than
        # redefining candidates; it must expose no SOURCE_CANDIDATES of its own.
        assert not hasattr(esr, "SOURCE_CANDIDATES")
        registry = get_source_registry()
        assert registry["schema_version"] == "oc-source-discovery-registry/v1"
        assert registry["graph_mutation"] is False
        assert registry["automatic_publication"] is False

    def test_adapter_paths_point_at_existing_files(self):
        for entry in esr.SOURCE_ID_RECONCILIATION.values():
            for rel in entry.existing_adapter_paths:
                assert (REPO_ROOT / rel).is_file(), f"{entry.source_id}: {rel}"

    def test_unrecognized_source_id_fails_closed(self, payload):
        broken = json.loads(json.dumps(payload))
        broken["sources"].append(
            {
                **json.loads(json.dumps(payload["sources"][0])),
                "source_id": "mystery_source",
                "verification_status": "verified_new",
                "data_license": "CC0",
                "media_license": "n/a",
                "commercial_use": "Yes",
                "ai_training_restriction": "None",
                "attribution_requirement": "None required",
            }
        )
        records = {r["source_id"]: r for r in esr.reconcile_sources(broken)}
        assert records["mystery_source"]["ingestion_gate"] == "blocked"
        assert not records["mystery_source"]["automated_ingestion_cleared"]

    def test_taxonomy_authorities_marked_as_mappings(self, reconciled):
        for sid in ("powo", "wcvp", "ipni", "wfo", "col", "ncbi_taxonomy"):
            assert reconciled[sid]["taxonomy_role"] == "authority_mapping", sid
        for sid, rec in reconciled.items():
            assert rec["taxonomy_role"] != "canonical_backbone", sid


# ---------------------------------------------------------------------------
# 3. License restrictions / fail-closed gating
# ---------------------------------------------------------------------------


class TestLicenseGating:
    def test_gate_counts(self, reconciled):
        gates = {sid: r["ingestion_gate"] for sid, r in reconciled.items()}
        assert set(sid for sid, g in gates.items() if g == "eligible") == EXPECTED_ELIGIBLE
        assert (
            set(sid for sid, g in gates.items() if g == "conditional")
            == EXPECTED_CONDITIONAL
        )
        assert set(sid for sid, g in gates.items() if g == "blocked") == EXPECTED_BLOCKED

    def test_speciesplus_blocked(self, reconciled):
        rec = reconciled["speciesplus"]
        assert rec["ingestion_gate"] == "blocked"
        assert not rec["automated_ingestion_cleared"]
        assert "verification_status" in rec["gate_rationale"] or "not retrievable" in (
            reconciled["speciesplus"]["gate_rationale"]
        )

    def test_all_unverified_statuses_blocked(self, reconciled, payload):
        unverified = {
            s["source_id"]
            for s in payload["sources"]
            if s["verification_status"] in esr.UNVERIFIED_STATUSES
        }
        assert unverified == {"plazi", "europepmc", "gnverifier", "try", "speciesplus"}
        for sid in unverified:
            assert reconciled[sid]["ingestion_gate"] == "blocked", sid
            assert not reconciled[sid]["automated_ingestion_cleared"], sid

    def test_iucn_blocked_on_restricted_terms(self, reconciled):
        assert reconciled["iucn"]["verification_status"] == "verified_new"
        assert reconciled["iucn"]["ingestion_gate"] == "blocked"

    def test_only_eligible_sources_cleared_for_automation(self, reconciled):
        for sid, rec in reconciled.items():
            assert rec["automated_ingestion_cleared"] == (
                rec["ingestion_gate"] == "eligible"
            ), sid

    def test_unknown_status_fails_closed(self):
        gate = esr.evaluate_ingestion_gate({"verification_status": "plausible"})
        assert gate is esr.IngestionGate.BLOCKED

    def test_missing_status_fails_closed(self):
        assert esr.evaluate_ingestion_gate({}) is esr.IngestionGate.BLOCKED

    def test_per_record_licensing_is_conditional_not_blocked(self, reconciled):
        # Verified sources with per-record licensing stay usable through
        # existing adapters but are not cleared for new automated ingestion.
        for sid in ("inat", "gbif", "bhl"):
            assert reconciled[sid]["ingestion_gate"] == "conditional", sid
            assert reconciled[sid]["existing_adapter_continuity"], sid

    def test_projected_candidates_never_auto_publish(self):
        for proj in esr.project_new_candidates():
            assert proj["graph_mutation"] is False
            assert proj["automatic_publication"] is False
            if proj["decision"] == "ADD":
                assert proj["admission_blockers"] == []
            else:
                assert proj["decision"] == "DEFER"
                assert proj["admission_blockers"], proj["source_id"]

    def test_projections_exclude_existing_candidates(self):
        existing_ids = {c["source_id"] for c in SOURCE_CANDIDATES}
        for proj in esr.project_new_candidates():
            assert proj["source_id"] not in existing_ids


# ---------------------------------------------------------------------------
# 4. Module-to-source lookup
# ---------------------------------------------------------------------------


class TestModuleLookup:
    def test_all_five_modules_bound_to_existing_code(self):
        for key in esr.MODULE_KEYS:
            binding = esr.MODULE_BINDINGS[key]
            assert (REPO_ROOT / binding["module_path"]).exists(), key

    def test_lookup_covers_every_module(self, payload):
        for key in esr.MODULE_KEYS:
            sources = esr.sources_for_module(key, payload)
            expected = set(payload["module_index"][key])
            assert {r["source_id"] for r in sources} == expected, key

    def test_lookup_returns_gate_information(self, payload):
        for rec in esr.sources_for_module("dossiers", payload):
            assert rec["ingestion_gate"] in {g.value for g in esr.IngestionGate}
            assert "automated_ingestion_cleared" in rec
            assert "attribution_requirement" in rec
            assert "recommended_citation" in rec

    def test_speciesplus_visible_but_blocked_in_dossiers(self, payload):
        dossier_sources = {
            r["source_id"]: r for r in esr.sources_for_module("dossiers", payload)
        }
        assert "speciesplus" in dossier_sources
        assert dossier_sources["speciesplus"]["ingestion_gate"] == "blocked"

    def test_unknown_module_raises(self):
        with pytest.raises(KeyError):
            esr.sources_for_module("phylogenetics")


# ---------------------------------------------------------------------------
# 5. World Plants backbone preservation
# ---------------------------------------------------------------------------


class TestBackbonePreservation:
    def test_assertion_passes_on_bundled_artifact(self, payload):
        esr.assert_backbone_preserved(payload)  # must not raise

    def test_canonical_authority_is_world_plants(self):
        assert esr.CANONICAL_TAXONOMIC_AUTHORITY == "world_plants"
        assert "Hassler" in esr.CANONICAL_TAXONOMIC_AUTHORITY_LABEL

    def test_live_canonical_taxonomy_module_unchanged(self):
        canonical = _load_module_from_path(
            "canonical_taxonomy_under_test",
            REPO_ROOT / "runtime" / "knowledge_graph" / "canonical_taxonomy.py",
        )
        assert canonical.CANONICAL_AUTHORITY == "world_plants"
        assert canonical.CANONICAL_AUTHORITY_LABEL == "World Plants (Dr. Michael Hassler)"

    def test_authority_labels_are_mappings_only(self):
        canonical = _load_module_from_path(
            "canonical_taxonomy_under_test_2",
            REPO_ROOT / "runtime" / "knowledge_graph" / "canonical_taxonomy.py",
        )
        mapping_labels = {
            entry.authority_label
            for entry in esr.SOURCE_ID_RECONCILIATION.values()
            if entry.taxonomy_role == "authority_mapping"
        }
        # Labels introduced by the artifact must be known mapping authorities:
        # either already in canonical_taxonomy.AUTHORITY_SOURCES or the two
        # additional vetted labels (WCVP, COL).
        assert mapping_labels <= set(canonical.AUTHORITY_SOURCES) | {"WCVP", "COL"}
        assert mapping_labels == {"POWO", "WCVP", "IPNI", "WFO", "COL", "NCBI"}

    def test_wcvp_cannot_become_backbone(self, payload):
        broken_entries = dict(esr.SOURCE_ID_RECONCILIATION)
        entry = broken_entries["wcvp"]
        broken_entries["wcvp"] = esr.ReconciliationEntry(
            source_id=entry.source_id,
            taxonomy_role="canonical_backbone",
            authority_label="WCVP",
        )
        original = esr.SOURCE_ID_RECONCILIATION
        try:
            esr.SOURCE_ID_RECONCILIATION = broken_entries
            with pytest.raises(esr.BackboneViolationError):
                esr.assert_backbone_preserved(payload)
        finally:
            esr.SOURCE_ID_RECONCILIATION = original

    def test_authority_mapping_with_unknown_label_rejected(self, payload):
        broken_entries = dict(esr.SOURCE_ID_RECONCILIATION)
        broken_entries["wcvp"] = esr.ReconciliationEntry(
            source_id="wcvp",
            taxonomy_role="authority_mapping",
            authority_label="SOME_RANDOM_BACKBONE",
        )
        original = esr.SOURCE_ID_RECONCILIATION
        try:
            esr.SOURCE_ID_RECONCILIATION = broken_entries
            with pytest.raises(esr.BackboneViolationError):
                esr.assert_backbone_preserved(payload)
        finally:
            esr.SOURCE_ID_RECONCILIATION = original


# ---------------------------------------------------------------------------
# 6. Compatibility with existing ingestion interfaces
# ---------------------------------------------------------------------------


def _ast_tree(rel_path: str) -> ast.Module:
    return ast.parse((REPO_ROOT / rel_path).read_text(encoding="utf-8"))


def _function_names(tree: ast.Module) -> set[str]:
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


class TestIngestionInterfaceCompatibility:
    def test_base_harvester_contract_unchanged(self):
        from harvesters.base import BaseHarvester

        for method in ("harvest_metadata", "harvest_images", "harvest_full"):
            assert callable(getattr(BaseHarvester, method)), method

    def test_traitbank_harvester_implements_base_contract(self):
        from harvesters.base import BaseHarvester
        from harvesters.traitbank import TraitBankHarvester

        assert issubclass(TraitBankHarvester, BaseHarvester)

    def test_inat_harvester_surfaces_license_and_attribution(self):
        # inat.py imports psycopg2 at module load; check statically instead.
        tree = _ast_tree("harvesters/inat.py")
        source_text = (REPO_ROOT / "harvesters/inat.py").read_text(encoding="utf-8")
        assert "license" in source_text
        assert "photographer" in source_text
        assert "harvest_images" in _function_names(tree)

    def test_gbif_harvester_surfaces_per_record_license(self):
        source_text = (REPO_ROOT / "harvesters/gbif_api.py").read_text(
            encoding="utf-8"
        )
        assert "license" in source_text
        assert "run" in _function_names(_ast_tree("harvesters/gbif_api.py"))

    def test_globi_interaction_harvester_requires_review(self):
        tree = _ast_tree("runtime/interaction_harvester.py")
        assert "harvest_interactions_once" in _function_names(tree)
        source_text = (REPO_ROOT / "runtime/interaction_harvester.py").read_text(
            encoding="utf-8"
        )
        assert "review_required" in source_text
        assert "automatic_publication" in source_text

    def test_literature_harvester_entry_points_intact(self):
        tree = _ast_tree("runtime/literature_harvester.py")
        names = _function_names(tree)
        assert "harvest_literature_once" in names
        # Crossref and Europe PMC paths used by the reconciliation map.
        assert any("crossref" in name for name in names)
        source_text = (REPO_ROOT / "runtime/literature_harvester.py").read_text(
            encoding="utf-8"
        )
        assert "europepmc" in source_text.lower() or "europe_pmc" in source_text.lower()

    def test_glossary_bridge_still_stages_candidates(self):
        bridge = _load_module_from_path(
            "glossary_intake_bridge_under_test",
            REPO_ROOT
            / "app"
            / "scientific_adapter_lab"
            / "glossary_intake_bridge.py",
        )
        assert bridge.BRIDGE_SCHEMA_VERSION == "oc-glossary-intake-bridge/v1"

    def test_report_carriers_governance_invariants(self):
        report = esr.reconciliation_report()
        assert report["graph_mutation"] is False
        assert report["automatic_publication"] is False
        assert report["canonical_taxonomic_authority"] == "world_plants"
        assert report["total_sources"] == EXPECTED_SOURCE_COUNT
        assert set(report["module_coverage"]) == set(esr.MODULE_KEYS)
        assert sorted(report["gates"]["blocked"]) == sorted(EXPECTED_BLOCKED)

    def test_report_is_json_serializable(self):
        json.dumps(esr.reconciliation_report())


# ---------------------------------------------------------------------------
# 7. Alignment with source-federation fail-closed rights semantics
# ---------------------------------------------------------------------------


class TestFederationAlignment:
    def test_rights_states_exist(self):
        from app.source_federation.inventory import RightsState

        assert {r.value for r in RightsState} == {"open", "restricted", "unknown"}

    def test_blocked_gates_match_uncertain_or_restricted_rights(self, payload, reconciled):
        # Every source whose licensing is restricted/uncertain per the
        # artifact must be gated BLOCKED — mirroring how
        # FederationCandidate.disposition fails closed on RESTRICTED/UNKNOWN.
        for source in payload["sources"]:
            sid = source["source_id"]
            status = source["verification_status"]
            haystack = " ".join(
                str(source.get(f, ""))
                for f in (
                    "data_license",
                    "media_license",
                    "commercial_use",
                    "ai_training_restriction",
                )
            ).lower()
            uncertain = status in esr.UNVERIFIED_STATUSES or any(
                m in haystack
                for m in ("strictly forbidden", "not retrievable", "unverified", "no cc license")
            )
            if uncertain:
                assert reconciled[sid]["ingestion_gate"] == "blocked", sid

    def test_existing_candidates_reused_not_duplicated(self, reconciled):
        # Reconciliation must reference the existing provider registry entries
        # rather than projecting duplicates for them.
        projected = {p["source_id"] for p in esr.project_new_candidates()}
        for sid, rec in reconciled.items():
            if rec["existing_candidate_id"] is not None:
                assert sid not in projected, sid
