from __future__ import annotations

from app.trait_genomics.molecular_harvester import (
    EuropePMCMolecularHarvester,
    MolecularHarvestTarget,
)


class FakeClient:
    def __init__(self, articles, annotations):
        self.articles = articles
        self.annotation_rows = annotations
        self.search_calls = []
        self.annotation_calls = []

    def search(self, scientific_name: str, *, page_size: int):
        self.search_calls.append((scientific_name, page_size))
        return list(self.articles)

    def annotations(self, article_id: str):
        self.annotation_calls.append(article_id)
        return list(self.annotation_rows)


class FullTextFakeClient(FakeClient):
    def __init__(self, articles, annotations, sections):
        super().__init__(articles, annotations)
        self.sections = sections
        self.full_text_calls = []

    def full_text_sections(self, pmcid: str):
        self.full_text_calls.append(pmcid)
        return list(self.sections)


class FakeRepository:
    def __init__(self):
        self.rows = []

    def upsert_candidate(self, candidate):
        row = candidate.model_dump(mode="json")
        row["association_id"] = candidate.stable_id()
        self.rows.append(row)
        return row


def target():
    return MolecularHarvestTarget(
        canonical_taxon_id="oc:orchid:1",
        scientific_name="Example orchid",
    )


def article(abstract: str):
    return {
        "pmid": "12345678",
        "pmcid": "PMC1234567",
        "doi": "10.1000/example",
        "title": "Molecular evolution of an orchid",
        "abstractText": abstract,
        "source": "MED",
    }


def annotation(name: str = "MYB1", uri: str = "https://identifiers.org/ncbigene:123"):
    return {
        "exact": name,
        "type": "Gene_Proteins",
        "section": "Abstract",
        "provider": "Europe PMC",
        "tags": [{"name": name, "uri": uri}],
    }


def test_harvester_requires_same_sentence_gene_trait_and_relation():
    client = FakeClient(
        [
            article(
                "Example orchid produces a strong fragrance. "
                "Expression of MYB1 was associated with floral scent intensity in sampled flowers."
            )
        ],
        [annotation()],
    )
    repository = FakeRepository()
    result = EuropePMCMolecularHarvester(client=client, repository=repository).harvest(
        [target()],
        page_size=10,
        persist=True,
    )

    assert result["diagnostics"]["candidates"] == 1
    assert result["diagnostics"]["persisted"] == 1
    assert result["review_required"] is True
    assert result["live_tig_eligible"] is False
    candidate = result["candidates"][0]
    assert candidate["evidence_kind"] == "expression_association"
    assert candidate["trait_predicate"] == "floral_scent"
    assert candidate["association_type"] == "associated_with"
    assert candidate["gene_id"] == "https://identifiers.org/ncbigene:123"
    assert candidate["evidence_text"].startswith("Expression of MYB1")
    assert repository.rows[0]["association_id"].startswith("tig-mol:")


def test_article_level_comention_without_sentence_relation_is_not_candidate():
    client = FakeClient(
        [article("MYB1 was sequenced in Example orchid. Floral scent was measured independently.")],
        [annotation()],
    )
    result = EuropePMCMolecularHarvester(client=client, repository=FakeRepository()).harvest(
        [target()], persist=False
    )
    assert result["diagnostics"]["candidates"] == 0
    assert result["diagnostics"]["skipped_no_trait_relation"] == 1


def test_relation_without_controlled_trait_is_not_candidate():
    client = FakeClient(
        [article("MYB1 expression was associated with drought tolerance in Example orchid.")],
        [annotation()],
    )
    result = EuropePMCMolecularHarvester(client=client, repository=FakeRepository()).harvest(
        [target()], persist=False
    )
    assert result["candidate_ids"] == []


def test_selection_language_preserves_selection_association_kind():
    client = FakeClient(
        [article("Selection on MYB1 was associated with flower color divergence in Example orchid.")],
        [annotation()],
    )
    result = EuropePMCMolecularHarvester(client=client, repository=FakeRepository()).harvest(
        [target()], persist=False
    )
    assert result["candidates"][0]["evidence_kind"] == "selection_association"
    assert result["candidates"][0]["trait_predicate"] == "flower_color"


def test_uniprot_annotation_is_retained_as_protein_identifier():
    client = FakeClient(
        [article("ABC1 was linked to floral morphology variation in Example orchid.")],
        [annotation("ABC1", "https://purl.uniprot.org/uniprot/Q9TEST1")],
    )
    result = EuropePMCMolecularHarvester(client=client, repository=FakeRepository()).harvest(
        [target()], persist=False
    )
    candidate = result["candidates"][0]
    assert candidate["protein_id"] == "https://purl.uniprot.org/uniprot/Q9TEST1"
    assert candidate["marker_name"] == "ABC1"


def test_dry_run_does_not_write_candidate_repository():
    repository = FakeRepository()
    client = FakeClient(
        [article("Expression of MYB1 was associated with floral scent in Example orchid.")],
        [annotation()],
    )
    result = EuropePMCMolecularHarvester(client=client, repository=repository).harvest(
        [target()], persist=False
    )
    assert result["diagnostics"]["candidates"] == 1
    assert result["diagnostics"]["persisted"] == 0
    assert repository.rows == []


def test_harvest_is_deterministic_for_same_source_evidence():
    client = FakeClient(
        [article("Expression of MYB1 was associated with floral scent in Example orchid.")],
        [annotation()],
    )
    harvester = EuropePMCMolecularHarvester(client=client, repository=FakeRepository())
    first = harvester.harvest([target()], persist=False)
    second = harvester.harvest([target()], persist=False)
    assert first["candidate_ids"] == second["candidate_ids"]


def test_later_gene_sentence_can_satisfy_same_sentence_gate():
    client = FakeClient(
        [
            article(
                "MYB1 was sequenced in Example orchid. "
                "Expression of MYB1 was associated with floral scent intensity in Example orchid."
            )
        ],
        [annotation()],
    )
    result = EuropePMCMolecularHarvester(client=client, repository=FakeRepository()).harvest(
        [target()], persist=False
    )
    assert result["diagnostics"]["candidates"] == 1
    assert result["candidates"][0]["evidence_text"].startswith("Expression of MYB1")
    assert result["candidates"][0]["provenance"]["evidence_scope"] == "abstract"


def test_open_access_full_text_fallback_preserves_sentence_gate_and_taxon_context():
    client = FullTextFakeClient(
        [article("MYB1 was sequenced in Example orchid without a reported floral association.")],
        [annotation()],
        [
            {
                "section": "Results",
                "text": (
                    "In Example orchid, expression of MYB1 was associated with flower color intensity. "
                    "Replicate measurements supported the pattern."
                ),
            }
        ],
    )
    result = EuropePMCMolecularHarvester(client=client, repository=FakeRepository()).harvest(
        [target()], persist=False
    )
    assert client.full_text_calls == ["PMC1234567"]
    assert result["diagnostics"]["full_text_attempted"] == 1
    assert result["diagnostics"]["full_text_available"] == 1
    assert result["diagnostics"]["full_text_candidates"] == 1
    assert result["diagnostics"]["candidates"] == 1
    candidate = result["candidates"][0]
    assert candidate["trait_predicate"] == "flower_color"
    assert candidate["provenance"]["evidence_scope"] == "open_access_full_text"
    assert candidate["provenance"]["evidence_section"] == "Results"


def test_full_text_fallback_does_not_assign_other_taxon_evidence_to_target():
    client = FullTextFakeClient(
        [article("MYB1 was sequenced in Example orchid without a reported floral association.")],
        [annotation()],
        [
            {
                "section": "Results",
                "text": "Expression of MYB1 was associated with flower color intensity in Another orchid.",
            }
        ],
    )
    result = EuropePMCMolecularHarvester(client=client, repository=FakeRepository()).harvest(
        [target()], persist=False
    )
    assert result["diagnostics"]["full_text_attempted"] == 1
    assert result["diagnostics"]["full_text_available"] == 1
    assert result["diagnostics"]["full_text_candidates"] == 0
    assert result["diagnostics"]["candidates"] == 0
