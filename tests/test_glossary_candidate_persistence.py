import json

import pytest

from app.literature_extraction.models import GlossaryTerm, Provenance
from app.scientific_synthesis.glossary_candidates import (
    CandidateConflictError,
    CandidatePersistenceError,
    GlossaryCandidateRecord,
    JsonGlossaryCandidateRepository,
)
from app.scientific_synthesis.language import BotanicalLanguageService


def _candidate(
    *,
    paper_id: str = "paper-1",
    source_hash: str = "a" * 64,
) -> GlossaryCandidateRecord:
    term = GlossaryTerm(
        term_id="term:labellum",
        term="Labellum",
        normalized_term="labellum",
        status="candidate",
        provenance=Provenance(
            method="rule_extracted",
            confidence=0.91,
            extractor="glossary-rules",
            extractor_version="1",
        ),
    )
    analysis = BotanicalLanguageService(
        lambda _term: {
            "resolution": "RESOLVED",
            "exact_concept_ids": ["concept-labellum"],
            "matches": [{"label": "labellum"}],
        }
    ).analyze_term(term.term, glossary_term=term)
    return GlossaryCandidateRecord.from_analysis(
        paper_id=paper_id,
        source_hash=source_hash,
        analysis=analysis,
    )


def test_candidate_identity_is_deterministic_and_source_bound():
    first = _candidate()
    replay = _candidate()
    other_source = _candidate(source_hash="b" * 64)

    assert first == replay
    assert first.candidate_id != other_source.candidate_id
    assert first.source_provenance["extractor"] == "glossary-rules"
    assert first.state == "MATCHED_PENDING_REVIEW"
    assert first.review_required is True
    assert first.canonical_promotion_authorized is False
    assert first.knowledge_graph_publication_authorized is False


def test_exact_replay_is_idempotent_across_repository_restart(tmp_path):
    candidate = _candidate()
    first_repository = JsonGlossaryCandidateRepository(tmp_path)

    first = first_repository.save(candidate)
    replay = JsonGlossaryCandidateRepository(tmp_path).save(candidate)

    assert first.created is True
    assert replay.created is False
    assert replay.candidate == candidate
    assert JsonGlossaryCandidateRepository(tmp_path).list() == [candidate]


def test_same_identity_with_changed_resolution_fails_closed(tmp_path):
    candidate = _candidate()
    repository = JsonGlossaryCandidateRepository(tmp_path)
    repository.save(candidate)
    changed = candidate.model_copy(
        update={"state": "UNRESOLVED", "matched_concept_id": None}
    )

    with pytest.raises(CandidateConflictError, match="different governed content"):
        repository.save(changed)

    assert repository.get(candidate.candidate_id) == candidate


def test_invalid_or_misidentified_persisted_records_fail_closed(tmp_path):
    candidate = _candidate()
    path = tmp_path / f"{candidate.candidate_id}.json"
    path.write_text("not-json", encoding="utf-8")

    with pytest.raises(CandidatePersistenceError, match="invalid persisted"):
        JsonGlossaryCandidateRepository(tmp_path).list()

    path.write_text(
        json.dumps(
            _candidate(source_hash="b" * 64).model_dump(mode="json"),
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    with pytest.raises(CandidatePersistenceError, match="does not match filename"):
        JsonGlossaryCandidateRepository(tmp_path).list()


def test_candidate_path_rejects_non_digest_identity(tmp_path):
    repository = JsonGlossaryCandidateRepository(tmp_path)

    with pytest.raises(ValueError, match="SHA-256"):
        repository.get("../candidate")
