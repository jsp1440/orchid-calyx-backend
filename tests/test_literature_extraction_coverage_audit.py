"""Tests for the TWO-DAY-SLICE-E literature corpus & extraction-coverage audit.

Pins four invariants:
  * stage separation -- one extraction stage never implies another;
  * masking detection is reused, not silently dropped, for the literature
    domain's discovered-corpus measurement;
  * bibliographic provenance (DOI) survives into the report;
  * unknown/unavailable is never coerced into zero, and this audit never
    writes -- to the database or to the bundle store.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.literature_extraction.coverage_audit import (
    audit_literature_extraction_coverage,
    discovered_corpus_measurement,
)
from app.literature_extraction.ingest import IngestedDocument
from app.literature_extraction.models import (
    AnalysisManifest,
    Entity,
    Identifier,
    PaperKnowledge,
    PaperMetadata,
    Provenance,
    PublicationDecision,
    Section,
    SourceDocument,
)
from app.literature_extraction.repository import LiteratureResultRepository


def _provenance() -> Provenance:
    return Provenance(method="source_reported", confidence=1.0)


def _document(text: str = "orchid velamen study") -> IngestedDocument:
    return IngestedDocument(
        source_path=Path("velamen-study.pdf"),
        raw_bytes=text.encode("utf-8"),
        raw_text=text,
        content_hash="sha256:0123456789abcdef",
    )


def _paper(
    *,
    paper_id: str,
    status: str = "completed",
    entities: list[Entity] | None = None,
    sections: list[Section] | None = None,
    publication_decisions: list[PublicationDecision] | None = None,
    dois: list[str] | None = None,
) -> PaperKnowledge:
    return PaperKnowledge(
        paper_id=paper_id,
        source=SourceDocument(
            content_hash="sha256:0123456789abcdef",
            media_type="application/pdf",
            original_filename="velamen-study.pdf",
        ),
        metadata=PaperMetadata(
            title="A study of orchid velamen",
            identifiers=[Identifier(scheme="doi", value=doi) for doi in (dois or [])],
        ),
        entities=entities or [],
        sections=sections or [],
        publication_decisions=publication_decisions or [],
        analysis_manifest=AnalysisManifest(
            analysis_id=f"analysis:{paper_id}:1",
            analysis_version=1,
            created_at=datetime.now(timezone.utc),
            pipeline_version="0.1.0",
            status=status,
        ),
    )


class RaisingCursor:
    """A cursor double that fails closed: any query it was not taught raises,
    and any write-shaped SQL raises regardless -- this audit must never issue
    one."""

    _FORBIDDEN = ("insert", "update", "delete", "merge", "drop", "truncate")

    def __init__(self, answers: dict[str, object]):
        self.answers = answers
        self.executed: list[str] = []
        self._result = None
        self._many: list = []

    def execute(self, sql, params=()):
        flat = " ".join(sql.lower().split())
        self.executed.append(flat)
        if any(word in flat for word in self._FORBIDDEN):
            raise AssertionError(f"read-only audit issued a write-shaped query: {flat}")
        if "to_regclass(%s) is not null" in flat:
            self._result = (params[0] in self.answers.get("schema", {}),)
        elif "from pg_class" in flat:
            name = params[0]
            rows = self.answers.get("rows", {})
            self._result = ("r", float(rows.get(name, 0))) if name in self.answers.get("schema", {}) else None
        elif "information_schema.columns" in flat:
            schema, table = params[0], params[1]
            cols = self.answers.get("schema", {}).get(f"{schema}.{table}", set())
            self._many = [(c,) for c in cols]
        elif flat.startswith("select doi from oc_graph.taxon_literature_edges"):
            if self.answers.get("kg_doi_lookup_fails"):
                raise RuntimeError("relation does not exist")
            self._many = [(doi,) for doi in self.answers.get("kg_dois", [])]
        elif flat.startswith("select count(*) from") and " join " in flat:
            self._result = (self.answers.get("joins", {}).get("matched", 0),)
        elif flat.startswith("select count(distinct"):
            self._result = (self.answers.get("joins", {}).get("taxa_reached", 0),)
        elif flat.startswith("select count(*) from") and " where " in flat:
            self._result = (self.answers.get("joins", {}).get("carrying", 0),)
        elif flat.startswith("select count(*) from"):
            table = flat[len("select count(*) from") :].strip()
            self._result = (self.answers.get("rows", {}).get(table, 0),)
        else:
            raise AssertionError(f"Unexpected SQL for this fake: {flat}")

    def fetchone(self):
        return self._result

    def fetchall(self):
        return self._many


TAXONOMY_SCHEMA = {"oc_taxonomy.taxa": {"taxon_id", "scientific_name"}}


def test_stage_separation_bound_entity_does_not_imply_extracted() -> None:
    """A paper can be bound to a taxon while its analysis failed. Neither
    stage may be inferred from the other."""
    paper = _paper(
        paper_id="paper-a",
        status="failed",
        entities=[
            Entity(
                entity_id="entity:taxon",
                entity_type="taxon",
                name="Phalaenopsis amabilis",
                external_ids=[Identifier(scheme="other", value="wcvp:123")],
                provenance=_provenance(),
            )
        ],
    )
    from app.literature_extraction.coverage_audit import _paper_coverage

    coverage = _paper_coverage(paper, full_text_available=True, kg_doi_index=None)
    assert coverage.taxonomically_bound is True
    assert coverage.extracted is False
    assert coverage.methods_extracted is False
    assert coverage.results_or_conclusions_extracted is False


def test_stage_separation_methods_and_results_are_independent() -> None:
    from app.literature_extraction.coverage_audit import _paper_coverage

    paper = _paper(
        paper_id="paper-b",
        sections=[
            Section(section_id="s1", canonical_type="methods", text="We measured...", order=0)
        ],
    )
    coverage = _paper_coverage(paper, full_text_available=True, kg_doi_index=None)
    assert coverage.methods_extracted is True
    assert coverage.results_or_conclusions_extracted is False


def test_discovered_corpus_measurement_flags_masking() -> None:
    """oc_literature.papers dwarfing the selected relation must be surfaced,
    reusing the relationship_measurement masking-detection path rather than
    silently promoting the larger table."""
    schema = {
        **TAXONOMY_SCHEMA,
        "oc_graph.taxon_literature_edges": {"taxon_edge_id", "scientific_name"},
        "oc_literature.papers": {"paper_id", "scientific_name"},
    }
    cur = RaisingCursor(
        {
            "schema": schema,
            "rows": {"oc_taxonomy.taxa": 31840, "oc_graph.taxon_literature_edges": 29, "oc_literature.papers": 6725},
            "joins": {"carrying": 29, "matched": 29, "taxa_reached": 29},
        }
    )
    result = discovered_corpus_measurement(cur)
    assert result["state"] == "present"
    assert result["object_table"] == "oc_graph.taxon_literature_edges"
    assert any("oc_literature.papers" in warning for warning in result["source_warnings"])


def test_unavailable_database_is_reported_not_absent_or_zero() -> None:
    """No live connection must yield 'unavailable', never 'absent' -- and the
    per-paper KG-materialization stage must be reported unknown, not zero."""
    repository = LiteratureResultRepository("/tmp/nonexistent-literature-root-xyz")
    result = audit_literature_extraction_coverage(None, repository)

    assert result["graph_mutation"] is False
    measurement = result["discovered_corpus"]["measurement"]
    assert measurement["state"] == "unavailable"
    assert "absent" in measurement["interpretation"]


def test_kg_doi_lookup_failure_is_unknown_not_false(tmp_path) -> None:
    repository = LiteratureResultRepository(tmp_path)
    paper = _paper(paper_id="paper-c", dois=["10.1234/example"])
    repository.save(paper, _document())

    schema = {
        **TAXONOMY_SCHEMA,
        "oc_graph.taxon_literature_edges": {"taxon_edge_id", "scientific_name"},
    }
    cur = RaisingCursor(
        {
            "schema": schema,
            "rows": {"oc_taxonomy.taxa": 31840, "oc_graph.taxon_literature_edges": 0},
            "joins": {"carrying": 0, "matched": 0, "taxa_reached": 0},
            "kg_doi_lookup_fails": True,
        }
    )
    result = audit_literature_extraction_coverage(cur, repository)
    pipeline = result["extraction_pipeline"]
    assert pipeline["papers_examined"] == 1
    assert pipeline["kg_materialized"] == 0
    assert pipeline["kg_materialized_unknown"] == 1


def test_doi_provenance_and_kg_materialization_survive_the_report(tmp_path) -> None:
    repository = LiteratureResultRepository(tmp_path)
    paper = _paper(paper_id="paper-d", dois=["10.9999/matched"])
    repository.save(paper, _document())

    schema = {
        **TAXONOMY_SCHEMA,
        "oc_graph.taxon_literature_edges": {"taxon_edge_id", "scientific_name"},
    }
    cur = RaisingCursor(
        {
            "schema": schema,
            "rows": {"oc_taxonomy.taxa": 31840, "oc_graph.taxon_literature_edges": 1},
            "joins": {"carrying": 1, "matched": 1, "taxa_reached": 1},
            "kg_dois": ["10.9999/matched"],
        }
    )
    result = audit_literature_extraction_coverage(cur, repository)
    provenance = result["extraction_pipeline"]["provenance"]
    assert len(provenance) == 1
    assert provenance[0]["doi_identifiers"] == ["10.9999/matched"]
    assert provenance[0]["kg_materialized"] is True
    assert result["extraction_pipeline"]["kg_materialized"] == 1


def test_publication_eligible_paper_never_mutates_the_graph(tmp_path) -> None:
    """A paper marked eligible_for_publication must still leave graph_mutation
    False -- eligibility is not a publication action."""
    repository = LiteratureResultRepository(tmp_path)
    paper = _paper(
        paper_id="paper-e",
        publication_decisions=[
            PublicationDecision(
                publication_decision_id="pd-1",
                review_item_id="ri-1",
                source_record_id="paper-e",
                status="eligible_for_publication",
            )
        ],
    )
    repository.save(paper, _document())

    result = audit_literature_extraction_coverage(None, repository)
    assert result["graph_mutation"] is False
    assert result["extraction_pipeline"]["stage_counts"]["publication_eligible"] == 1


def test_list_paper_ids_skips_partial_bundles_and_missing_root(tmp_path) -> None:
    repository = LiteratureResultRepository(tmp_path / "missing")
    assert repository.list_paper_ids() == []
    assert repository.root_available() is False

    repository = LiteratureResultRepository(tmp_path)
    (tmp_path / "partial-bundle").mkdir()
    paper = _paper(paper_id="paper-f")
    repository.save(paper, _document())

    assert repository.list_paper_ids() == ["paper-f"]
    assert repository.root_available() is True
