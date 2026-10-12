"""Provider-free scientific convergence integration tests.

Covers the integrated pathway across the pre-existing modules:

    botanical description -> anatomical concept -> character/state
    -> taxonomic context -> Lexicon reference -> Matrix evidence
    -> KG-compatible output

Brain-side tests (OAO-Lexicon-Matrix-KG bridge) skip gracefully when the Brain
checkout is unavailable (OC_BRAIN_ROOT unset or bridge module missing); Calyx-side
tests always run. No network, no paid providers, no production data.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
CALYX_ROOT = Path(os.environ.get("OC_CALYX_ROOT", HERE.parents[2]))
BRAIN_ROOT = Path(os.environ.get("OC_BRAIN_ROOT", CALYX_ROOT.parent / "brain"))

for path in (str(CALYX_ROOT), str(BRAIN_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from app.scientific_adapter_lab.kg_materialization import (  # noqa: E402
    KGEvidenceState,
    KGMaterializationRecord,
    KnowledgeGraphPipeline,
    SourceDomain,
)
from runtime.matrix_identification_registry import (  # noqa: E402
    Candidate,
    RegistryCharacter,
    create_registry_version,
)
from runtime.matrix_identification_session import (  # noqa: E402
    add_observation,
    create_session,
    evaluate_session,
)
from runtime.matrix_taxon_resolution import (  # noqa: E402
    StaticTaxonResolver,
    TaxonEntry,
)

try:
    from tools import oao_lexicon_matrix_kg_bridge as brain_bridge
except ImportError:  # pragma: no cover - Brain checkout unavailable
    brain_bridge = None

BRAIN_FIXTURES = BRAIN_ROOT / "fixtures" / "oao_bridge"
brain_unavailable = pytest.mark.skipif(
    brain_bridge is None or not BRAIN_FIXTURES.is_dir(),
    reason="Brain checkout with OAO bridge fixtures not available (set OC_BRAIN_ROOT)",
)


@pytest.fixture()
def bridge():
    return brain_bridge.OaoLexiconMatrixKgBridge(
        eq_mappings=brain_bridge.load_oao_eq_mappings(
            BRAIN_ROOT / brain_bridge.OAO_EQ_MAPPINGS_PATH
        ),
        term_registry=brain_bridge.load_oao_term_registry(
            BRAIN_ROOT / brain_bridge.OAO_TERM_REGISTRY_PATH
        ),
        lexicon=brain_bridge.load_lexicon_export(
            BRAIN_FIXTURES / "lexicon_export_fixture.json"
        ),
        accessions=brain_bridge.load_accession_table(
            BRAIN_FIXTURES / "oao_accession_resolution_slice.csv"
        ),
    )


@pytest.fixture()
def representative_evidence():
    payload = json.loads(
        (BRAIN_FIXTURES / "representative_orchid_evidence.json").read_text(
            encoding="utf-8"
        )
    )
    return payload["observations"]


def _as_calyx_record(payload: dict) -> KGMaterializationRecord:
    """Re-express a Brain bridge KG record under the real Calyx contract."""
    return KGMaterializationRecord(
        record_id=payload["record_id"],
        source_domain=SourceDomain(payload["source_domain"]),
        evidence_state=KGEvidenceState(payload["evidence_state"]),
        taxon_id=payload["taxon_id"],
        taxon_name=payload["taxon_name"],
        subject_entity=payload["subject_entity"],
        predicate=payload["predicate"],
        object_entity=payload["object_entity"],
        provenance_chain=tuple(payload["provenance_chain"]),
        human_review_required=payload["human_review_required"],
        schema_version=payload["schema_version"],
    )


# --------------------------------------------------------------------------
# Calyx-side governance (always runs)
# --------------------------------------------------------------------------


def test_kg_pipeline_refuses_automatic_publication():
    with pytest.raises(ValueError, match="KG_PIPELINE_GOVERNANCE_VIOLATION"):
        KnowledgeGraphPipeline(automatic_publication=True)


def test_kg_pipeline_refuses_knowledge_graph_mutation():
    with pytest.raises(ValueError, match="KG_PIPELINE_GOVERNANCE_VIOLATION"):
        KnowledgeGraphPipeline(knowledge_graph_mutation=True)


def test_taxon_resolution_exact_only_never_fabricates():
    resolver = StaticTaxonResolver(
        [
            TaxonEntry(
                "world-plants:cattleya-labiata",
                "Cattleya labiata",
                synonyms=("C. labiata",),
            )
        ]
    )
    exact = resolver.resolve("Cattleya labiata")
    assert exact.resolution_state == "resolved_canonical"
    assert exact.canonical_taxon_id == "world-plants:cattleya-labiata"

    synonym = resolver.resolve("C. labiata")
    assert synonym.resolution_state == "resolved_synonym"
    assert synonym.canonical_taxon_id == "world-plants:cattleya-labiata"

    unresolved = resolver.resolve("Cattleya sp.")
    assert unresolved.resolution_state == "unresolved"
    assert unresolved.canonical_taxon_id is None

    near_miss = resolver.resolve("Cattleya labiataa")  # no fuzzy matching
    assert near_miss.resolution_state == "unresolved"


def test_matrix_registry_session_report_roundtrip(tmp_path):
    registry_root = tmp_path / "registries"
    session_root = tmp_path / "sessions"
    margin_uuid = "bb7aba9f-a620-44ee-9427-12369441eb81"  # OAO:0000007
    create_registry_version(
        registry_id="cattleya-it",
        version="1",
        title="Cattleya bounded diagnostic matrix (integration test)",
        scope={"genus": "Cattleya"},
        characters=[
            RegistryCharacter(
                "labellum_margin",
                "Labellum margin",
                weight=3,
                concept_id=margin_uuid,
                provenance={"oao_character_id": "OAO:0000007"},
            )
        ],
        candidates=[
            Candidate(
                "world-plants:cattleya-labiata",
                "Cattleya labiata",
                {"labellum_margin": "fimbriate"},
            ),
            Candidate(
                "world-plants:cattleya-mossiae",
                "Cattleya mossiae",
                {"labellum_margin": "crenulate"},
            ),
        ],
        provenance={"source": "integration test governed assertions"},
        actor="integration-test",
        root=registry_root,
    )
    session = create_session(
        registry_id="cattleya-it",
        version="1",
        actor="integration-test",
        root=session_root,
        registry_root=registry_root,
    )
    add_observation(
        session["session_id"],
        character="labellum_margin",
        value="fimbriate",
        certainty="certain",
        source={"kind": "botanical_description", "review_state": "review_required"},
        actor="integration-test",
        access_actor="integration-test",
        root=session_root,
        registry_root=registry_root,
    )
    evaluation = evaluate_session(
        session["session_id"],
        access_actor="integration-test",
        root=session_root,
        registry_root=registry_root,
    )
    leader = evaluation["report"]["candidates"][0]
    assert leader["taxon_id"] == "world-plants:cattleya-labiata"


def test_matrix_registry_rejects_non_uuid_concept_id(tmp_path):
    with pytest.raises(ValueError, match="canonical concept UUID"):
        create_registry_version(
            registry_id="bad-concept",
            version="1",
            title="invalid",
            scope={},
            characters=[
                RegistryCharacter("c1", "C1", concept_id="OAO:0000007")
            ],
            candidates=[Candidate("t1", "Taxon one", {"c1": "x"})],
            provenance={"source": "integration test"},
            actor="integration-test",
            root=tmp_path,
        )


# --------------------------------------------------------------------------
# Cross-repo pathway (skip without Brain checkout)
# --------------------------------------------------------------------------


@brain_unavailable
def test_bridge_kg_records_validate_under_calyx_contract(
    bridge, representative_evidence
):
    result = bridge.ingest_evidence(representative_evidence[0])
    assert result["lexicon_concept"]["slug"] == "labellum"
    assert result["oao_state_matched"]["oao_id"] == "OAO:0000017"

    records = [_as_calyx_record(p) for p in result["kg_records"]]
    assert len(records) == 3
    for record in records:
        record.validate()  # raises on any Calyx contract violation
        assert record.human_review_required is True
        assert record.evidence_state is KGEvidenceState.CANONICAL_UNREVIEWED
        assert record.source_domain is SourceDomain.TRAITS
    # Lexicon reference rides in the provenance chain as lexicon:<id>:<slug>
    assert any(
        entry.startswith("lexicon:") and entry.endswith(":labellum")
        for record in records
        for entry in record.provenance_chain
    )


@brain_unavailable
def test_canonical_concept_uuids_come_from_oao_term_registry(bridge):
    uuid_map = {
        row.oao_id: row.registry_id
        for row in brain_bridge.load_oao_term_registry(
            BRAIN_ROOT / brain_bridge.OAO_TERM_REGISTRY_PATH
        )
    }
    # Every concept id the Matrix would bind to is a genuine UUID
    for oao_id, concept_uuid in uuid_map.items():
        assert str(uuid.UUID(concept_uuid)) == concept_uuid, oao_id
    # Known canonical bindings used by the convergence demo
    assert uuid_map["OAO:0000007"] == "bb7aba9f-a620-44ee-9427-12369441eb81"
    assert uuid_map["OAO:0000008"] == "35e67796-fbb7-4d29-86ee-769e084a6c8e"


@brain_unavailable
def test_conflicting_evidence_preserved_not_collapsed(
    bridge, representative_evidence
):
    conflict_pair = [
        obs
        for obs in representative_evidence
        if "Stanhopea" in obs.get("taxon_name", "")
    ]
    assert len(conflict_pair) == 2
    batch = bridge.ingest_evidence_batch(conflict_pair)
    conflicts = batch["conflicts"]
    assert len(conflicts) == 1
    assert conflicts[0]["resolution"] == "preserved_not_collapsed"
    assert set(conflicts[0]["conflicting_states"]) == {
        "Spur presence — absent",
        "Spur presence — present",
    }
    # Both conflicting observations still emit their own review-bound KG records
    for result in batch["results"]:
        records = [_as_calyx_record(p) for p in result["kg_records"]]
        for record in records:
            record.validate()
            assert record.human_review_required is True
