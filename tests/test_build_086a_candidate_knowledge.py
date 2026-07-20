from pathlib import Path

from app.candidate_knowledge.models import CandidateKind, EvidenceInput, SourceAnchor
from app.candidate_knowledge.repository import MemoryCandidateRepository
from app.candidate_knowledge.service import CandidateExtractionService


def evidence(source_id=1, anchor_id=11, policy="FULL_TEXT_ALLOWED", facts=None, text="Masdevallia occurs in cloud forest."):
    metadata = {"subject": "Masdevallia", "source_confidence": 0.8}
    if facts is not None:
        metadata["candidate_facts"] = facts
    return EvidenceInput("TAXONOMIC_TREATMENT", source_id, source_id, source_id, text, (SourceAnchor(anchor_id, page_number=2, char_start=0, char_end=len(text), locator={"page": 2, "confidence": 0.95}),), display_policy=policy, internal_use_permission=policy == "INTERNAL_RESEARCH_ONLY", metadata=metadata)


def setup():
    repository = MemoryCandidateRepository()
    return repository, CandidateExtractionService(repository)


def test_additive_migration_is_isolated_and_candidate_only():
    sql = Path("migrations/086a_candidate_knowledge.sql").read_text()
    upper = sql.upper()
    assert "CREATE SCHEMA IF NOT EXISTS OC_CANDIDATE_KNOWLEDGE" in upper
    assert "OC_DOCUMENT_INTELLIGENCE.EXTRACTION_RUNS" in upper
    assert "OC_DOCUMENT_INTELLIGENCE.SOURCE_ANCHORS" in upper
    assert "PUBLISHED BOOLEAN NOT NULL DEFAULT FALSE CHECK(PUBLISHED = FALSE)" in upper
    assert all(token not in upper for token in ("DROP ", "TRUNCATE ", "OC_GRAPH.", "OC_TAXONOMY."))


def test_preview_execute_preserves_source_identity_anchor_and_provenance():
    repository, service = setup()
    plan = service.preview([evidence()])
    assert plan["candidates_created"] == 0 and plan["published_nodes"] == plan["published_edges"] == 0
    result = service.execute(plan["candidate_run_id"])
    assert result["state"] == "COMPLETED"
    candidate = repository.candidates[0]
    link = repository.evidence_links[0]
    assert candidate["kind"] == CandidateKind.GEOGRAPHIC_OCCURRENCE
    assert candidate["published"] is False and candidate["review_state"] == "REQUIRED"
    assert link["revision_id"] == link["extraction_run_id"] == 1
    assert link["anchor"]["anchor_id"] == 11 and link["anchor"]["locator"]["page"] == 2


def test_all_required_candidate_domains_accept_structured_reviewable_facts():
    repository, service = setup()
    kinds = list(CandidateKind)
    facts = [{"kind": kind.value, "subject": "Taxon A", "predicate": f"predicate_{index}", "object_value": f"value_{index}", "confidence": 0.7} for index, kind in enumerate(kinds)]
    plan = service.preview([evidence(facts=facts)])
    service.execute(plan["candidate_run_id"])
    assert {x["kind"] for x in repository.candidates} == {x.value for x in kinds}
    assert all(not x["published"] for x in repository.candidates)
    assert len(repository.reviews) == len(kinds)


def test_idempotency_duplicates_conflicts_and_version_history():
    repository, service = setup()
    facts = [{"kind": "TRAIT", "subject": "Taxon A", "predicate": "flower_color", "object_value": "red"}]
    first = service.preview([evidence(facts=facts)])
    service.execute(first["candidate_run_id"])
    same = service.preview([evidence(facts=facts)])
    assert same["counts"] == {"REUSE": 1}
    service.execute(same["candidate_run_id"])
    assert len(repository.candidates) == 1
    duplicate = service.preview([evidence(2, 22, facts=facts)])
    service.execute(duplicate["candidate_run_id"])
    assert duplicate["counts"] == {"EXTRACT": 1} and repository.duplicate_groups
    assert {x["anchor"]["anchor_id"] for x in repository.evidence_links} == {11, 22}
    conflict_facts = [{"kind": "TRAIT", "subject": "Taxon A", "predicate": "flower_color", "object_value": "yellow"}]
    conflict = service.preview([evidence(3, 33, facts=conflict_facts)])
    service.execute(conflict["candidate_run_id"])
    assert repository.conflicts and repository.runs[conflict["candidate_run_id"]]["metrics"]["conflicts"] == 1
    assert [x["version"] for x in repository.candidates] == [1, 2]
    assert sum(x["active"] for x in repository.candidates) == 1


def test_cancellation_resume_preserves_completed_boundary():
    repository, service = setup()
    plan = service.preview([evidence(), evidence(2, 22, text="Masdevallia flowers in May.")])
    service.cancel(plan["candidate_run_id"])
    assert service.execute(plan["candidate_run_id"])["state"] == "CANCELLED"
    result = service.resume(plan["candidate_run_id"])
    assert result["state"] == "COMPLETED" and result["last_completed_item_id"] is not None
    assert len(repository.candidates) == 2


def test_copyright_controls_never_leak_restricted_text():
    repository, service = setup()
    restricted = evidence(policy="METADATA_ONLY", text="Masdevallia occurs in secret protected locality.")
    plan = service.preview([restricted])
    service.execute(plan["candidate_run_id"])
    assert repository.evidence_links[0]["authorized_quote"] is None
    limited = evidence(2, 22, policy="LIMITED_PREVIEW_ONLY", text="Masdevallia occurs in a very long cloud forest locality.")
    limited = EvidenceInput(**{**limited.__dict__, "metadata": {**limited.metadata, "excerpt_limit": 12}})
    run = service.preview([limited])
    service.execute(run["candidate_run_id"])
    assert len(repository.evidence_links[-1]["authorized_quote"]) == 12


def test_review_decisions_are_audited_but_never_publish():
    repository, service = setup()
    plan = service.preview([evidence()])
    service.execute(plan["candidate_run_id"])
    review_id = next(iter(repository.reviews))
    repository.resolve_review(review_id, "APPROVE_CANDIDATE", "Anchor and normalization verified", "owner")
    assert repository.candidates[0]["review_state"] == "APPROVED"
    assert repository.candidates[0]["published"] is False and repository.events


def test_api_and_source_contract_have_no_publication_surface():
    from app.candidate_knowledge.routes import router

    mutating = [route for route in router.routes if getattr(route, "methods", set()) & {"PUT", "PATCH", "DELETE"}]
    assert not mutating
    code = "\n".join(path.read_text() for path in Path("app/candidate_knowledge").glob("*.py"))
    assert all(token not in code for token in ("production_publish", "publish_node", "publish_edge", "drive.files.update"))
