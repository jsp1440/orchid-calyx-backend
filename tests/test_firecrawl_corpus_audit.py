"""Scientific relevance and fail-closed corpus audit boundaries."""
import pytest

from app.literature_extraction.corpus_audit import (
    _genre,
    _identity,
    _relevance,
    audit_existing_corpus,
    load_corpus_document,
)


def test_monograph_body_is_relevant_without_taxon_in_title():
    row = {"title": "A monograph of slipper orchids", "full_text": "Paphiopedilum delenatii leaf length 7 cm."}
    assert _relevance(row, "Paphiopedilum", ["Paphiopedilum delenatii"]) == (["Paphiopedilum delenatii"], True)
    assert _genre(row) == "monograph"


def test_taxon_metadata_and_exact_names_not_title_or_substring():
    assert _relevance({"metadata": {"taxa": ["Paphiopedilum delenatii"]}}, "Paphiopedilum", ["Paphiopedilum delenatii"])[1]
    assert not _relevance({"title": "Paphiopedilum monograph"}, "Paphiopedilum", [])[1]
    assert not _relevance({"full_text": "NotPaphiopedilumlike"}, "Paphiopedilum", [])[1]


def test_report_identity_does_not_leak_full_text_or_locality():
    identity = _identity({"title": "Flora", "sha256": "a" * 64, "provenance": {"source_url": "https://example.org/flora"}, "full_text": "private locality", "latitude": 23})
    assert identity["content_hash"] == "a" * 64
    assert identity["source_url"] == "https://example.org/flora"
    assert "private" not in str(identity)
    assert "latitude" not in identity


def test_unavailable_database_never_reports_complete_or_empty_corpus():
    def unavailable():
        raise ConnectionError("sensitive connection string")
    report = audit_existing_corpus(unavailable, genus="Paphiopedilum")
    assert not report["available"] and not report["complete"]
    assert report["blockers"] == ["CORPUS_AUDIT_UNAVAILABLE:ConnectionError"]
    assert "sensitive" not in str(report)


def test_unknown_legacy_document_cannot_be_loaded_as_canonical_revision():
    with pytest.raises(ValueError, match="NOT_LOADABLE"):
        load_corpus_document(lambda: pytest.fail("must not open database"), {"relation": "public.research_documents"})


@pytest.mark.parametrize("kwargs", [{"genus": "Paphiopedilum;"}, {"genus": "Paphiopedilum", "taxon_names": ["Cattleya labiata"]}, {"genus": "Paphiopedilum", "max_rows": 0}])
def test_invalid_audit_scope_fails_before_database(kwargs):
    with pytest.raises(ValueError):
        audit_existing_corpus(lambda: pytest.fail("must not open database"), **kwargs)


def test_opaque_title_only_document_has_undetermined_relevance():
    from app.literature_extraction.corpus_audit import _relevance_assessable
    assert not _relevance_assessable({"title": "Paphiopedilum revision", "content_bytes": b"%PDF"})
    assert _relevance_assessable({"metadata": {"taxa": ["Cattleya labiata"]}})


def test_audit_cli_summary_has_counts_only():
    from scripts.oc_literature_corpus_audit import public_counts
    summary = public_counts({"schema": "audit", "available": True, "complete": False, "relations": {},
                             "documents": [{"genre": "flora", "source_url": "secret", "title": "locality"}],
                             "blockers": ["CORPUS_RELEVANCE_UNDETERMINED:private-id"]})
    assert summary["blocker_counts"] == {"CORPUS_RELEVANCE_UNDETERMINED": 1}
    assert "secret" not in str(summary) and "locality" not in str(summary) and "private-id" not in str(summary)
