from types import SimpleNamespace

from app.literature_extraction.models import Entity
from runtime.knowledge_graph import globi_corpus_backfill as backfill
from runtime.knowledge_graph.publisher import canonical_key
from tests.test_publication_eligible_paper_graph import _paper, _prov


def _interaction_paper():
    paper = _paper()
    paper.entities.append(
        Entity(
            entity_id="taxon-2",
            entity_type="taxon",
            name="Apis mellifera",
            normalized_name="Apis mellifera",
            provenance=_prov("accepted"),
        )
    )
    paper.claims[0].subject_ids = ["taxon-2"]
    paper.claims[0].object_ids = ["taxon-1"]
    paper.claims[0].predicate = "visits flowers of"
    return paper


def test_backfill_reprocesses_existing_reviewed_papers_without_writes(monkeypatch):
    paper = _interaction_paper()

    class Papers:
        def __init__(self, root):
            self.root = root

        def get(self, paper_id):
            return paper if paper_id == paper.paper_id else None

        def get_raw_bytes(self, paper_id):
            return b"immutable-source"

    class Binding:
        source_object_type = "LITERATURE_DOCUMENT"
        source_object_id = 77
        fingerprint = "binding-1"

        def validate_integrity(self, loaded_paper, raw_bytes):
            assert loaded_paper is paper
            assert raw_bytes == b"immutable-source"

    class Bindings:
        def __init__(self, root):
            self.root = root

        def get(self, paper_id):
            return Binding() if paper_id == paper.paper_id else None

    resolution = SimpleNamespace(
        keys_by_entity_id={
            "taxon-1": canonical_key("taxon", 42),
            "taxon-2": canonical_key("taxon", 101),
        }
    )
    monkeypatch.setattr(backfill, "_paper_ids", lambda *args, **kwargs: [paper.paper_id])
    monkeypatch.setattr(backfill, "LiteratureResultRepository", Papers)
    monkeypatch.setattr(backfill, "FileLiteratureSourceBindingRepository", Bindings)
    monkeypatch.setattr(
        backfill,
        "resolve_exact_taxon_keys_for_paper",
        lambda dsn, loaded_paper: resolution,
    )

    report = backfill.scan_existing_literature_for_globi_candidates(
        "postgresql://read-only-test",
        root="unused",
    )

    assert report["read_only"] is True
    assert report["knowledge_graph_mutation"] is False
    assert report["external_submission"] is False
    assert report["papers_scanned"] == 1
    assert report["candidate_count"] == 1
    candidate = report["candidates"][0]
    assert candidate["source_taxon_name"] == "Apis mellifera"
    assert candidate["interaction_type"] == "visitsFlowersOf"
    assert candidate["target_taxon_name"] == "Laelia anceps"
    assert candidate["interaction_type_ro_uri"].endswith("RO_0002622")
    assert candidate["novelty_status"] == "not_checked_against_globi"
    assert candidate["claim_statement"]
    assert candidate["evidence"]


def test_supplied_globi_snapshot_classifies_candidate_novelty(monkeypatch):
    paper = _interaction_paper()

    class Papers:
        def __init__(self, root):
            pass

        def get(self, paper_id):
            return paper

        def get_raw_bytes(self, paper_id):
            return b"source"

    class Binding:
        source_object_type = "LITERATURE_DOCUMENT"
        source_object_id = 77
        fingerprint = "binding-1"

        def validate_integrity(self, loaded_paper, raw_bytes):
            return None

    class Bindings:
        def __init__(self, root):
            pass

        def get(self, paper_id):
            return Binding()

    monkeypatch.setattr(backfill, "_paper_ids", lambda *args, **kwargs: [paper.paper_id])
    monkeypatch.setattr(backfill, "LiteratureResultRepository", Papers)
    monkeypatch.setattr(backfill, "FileLiteratureSourceBindingRepository", Bindings)
    monkeypatch.setattr(
        backfill,
        "resolve_exact_taxon_keys_for_paper",
        lambda dsn, loaded_paper: SimpleNamespace(
            keys_by_entity_id={
                "taxon-1": canonical_key("taxon", 42),
                "taxon-2": canonical_key("taxon", 101),
            }
        ),
    )

    report = backfill.scan_existing_literature_for_globi_candidates(
        "postgresql://read-only-test",
        root="unused",
        known_globi_interactions={
            ("Apis mellifera", "visitsFlowersOf", "Laelia anceps")
        },
    )
    assert report["novelty_checked_against_globi"] is True
    assert report["candidates"][0]["novelty_status"] == (
        "already_present_in_supplied_globi_snapshot"
    )


def test_globi_export_rows_preserve_reference_and_ro_identity():
    report = {
        "candidates": [
            {
                "source_taxon_name": "Apis mellifera",
                "interaction_type": "visitsFlowersOf",
                "interaction_type_ro_uri": "http://purl.obolibrary.org/obo/RO_0002622",
                "target_taxon_name": "Laelia anceps",
                "doi": "10.1234/example",
                "title": "Pollination study",
                "paper_id": "paper-1",
                "claim_id": "claim-1",
                "claim_statement": "Apis mellifera visits flowers of Laelia anceps.",
            }
        ]
    }
    rows = backfill.globi_tsv_rows(report)
    assert rows == [
        {
            "sourceTaxonName": "Apis mellifera",
            "interactionTypeName": "visitsFlowersOf",
            "interactionTypeId": "http://purl.obolibrary.org/obo/RO_0002622",
            "targetTaxonName": "Laelia anceps",
            "referenceDoi": "10.1234/example",
            "referenceCitation": "Pollination study",
            "referenceUrl": None,
            "sourceId": "orchid-continuum:paper-1:claim-1",
            "sourceCitation": "Orchid Continuum literature-derived interaction",
            "notes": "Apis mellifera visits flowers of Laelia anceps.",
        }
    ]
