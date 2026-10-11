"""End-to-end tests for the offline scientific workflow.

Demonstrates, with executable assertions, the mission pipeline:

1. an authorised botanical description is loaded from a test fixture;
2. its scientific name is resolved;
3. botanical terminology is matched to Lexicon definitions;
4. morphological characters are extracted;
5. character evidence is stored with provenance;
6. the Species Dossier displays the supported information;
7. the Matrix retrieves and compares the characters;
8. the Illustrated Glossary supplies definitions and illustration state.

All fixtures are deterministic and offline; no database, network or paid
provider is touched.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.literature_extraction.context import PipelineConfig
from app.literature_extraction.registry import DEFAULT_REGISTRY, ExtractorRegistry
from app.literature_extraction.repository import LiteratureResultRepository
from app.literature_extraction.service import extract_and_persist
from app.scientific_workflow import (
    CHARACTERS,
    CharacterEvidenceStore,
    CuratedTerminologyService,
    FixtureLayout,
    FixtureTaxonResolver,
    IllustrationRegistry,
    StateKind,
    build_glossary_entry,
    extract_characters,
    parse_description_text,
    run_workflow,
)
from app.scientific_workflow.graph_bridge import build_graph_slice
from app.scientific_workflow.literature_pipeline import MorphologyExtractor
from app.scientific_workflow.matrix_bridge import (
    candidates_from_evidence,
    observations_from_views,
)

FIXTURES = FixtureLayout(Path(__file__).parent / "fixtures" / "scientific_workflow")
DESCRIPTIONS = sorted(FIXTURES.descriptions_dir.glob("*.txt"))

CYPRIPEDIUM = "oc-taxon:cypripedium-calceolus"
CATTLEYA = "oc-taxon:cattleya-labiata"
VANDA = "oc-taxon:vanda-coerulea"
RHIZANTHELLA = "oc-taxon:rhizanthella-gardneri"


@pytest.fixture(scope="module")
def terminology() -> CuratedTerminologyService:
    return CuratedTerminologyService(FIXTURES.lexicon_terms_csv, FIXTURES.oao_accessions_csv)


@pytest.fixture(scope="module")
def resolver() -> FixtureTaxonResolver:
    return FixtureTaxonResolver(FIXTURES.taxa_csv)


def _parse(name: str):
    return parse_description_text(
        (FIXTURES.descriptions_dir / name).read_text(encoding="utf-8"),
        fallback_source_id=name,
    )


def _records(name: str, taxon_id: str):
    return {record.character_id: record for record in extract_characters(_parse(name), taxon_id)}


# ---------------------------------------------------------------------------
# Step 1+2 — acquisition (fixture load) and taxon resolution
# ---------------------------------------------------------------------------


class TestFixtureAcquisitionAndResolution:
    def test_fixture_front_matter_parsed_with_rights(self):
        parsed = _parse("cypripedium_calceolus.txt")
        assert parsed.citation.source_id == "FIX-DESC-CYPCAL-001"
        assert parsed.citation.source_type == "synthetic_test_fixture"
        assert parsed.citation.rights_status == "open_license"
        assert parsed.taxon_name == "Cypripedium calceolus L."
        assert parsed.body_offset > 0

    def test_resolution_with_and_without_authorship(self, resolver):
        with_authorship = resolver.resolve("Cypripedium calceolus L.")
        bare = resolver.resolve("cypripedium   calceolus")
        assert with_authorship.status == bare.status == "resolved"
        assert with_authorship.taxon.taxon_id == CYPRIPEDIUM
        assert with_authorship.taxon.full_scientific_name == "Cypripedium calceolus L."

    def test_unresolved_name_is_not_guessed(self, resolver):
        result = resolver.resolve("Paphiopedilum insigne")
        assert result.status == "unresolved"
        assert result.taxon is None
        assert "left unresolved" in result.explanation

    def test_garbage_name_is_invalid_not_resolved(self, resolver):
        assert resolver.resolve("not a taxon").status == "unresolved"


# ---------------------------------------------------------------------------
# Step 3 — terminology normalisation against the Lexicon
# ---------------------------------------------------------------------------


class TestTerminology:
    def test_text_matching_finds_orchid_terms(self, terminology):
        parsed = _parse("vanda_coerulea.txt")
        matched = {match.term.term_id for match in terminology.match_text(parsed.body)}
        assert {"pseudobulb", "labellum", "floral_spur", "pollinium", "viscidium", "resupination"} <= matched

    def test_accessions_keep_verified_and_rejected_rows(self, terminology):
        rows = terminology.accessions_for("labellum")
        usable = [row for row in rows if row.is_usable]
        rejected = [row for row in rows if row.status == "rejected"]
        assert [row.accession for row in usable] == ["FLOPO:0980978"]
        # BTO:0004875 (animal anatomy) stays visible as verified negative evidence.
        assert [row.accession for row in rejected] == ["BTO:0004875"]

    def test_extension_gaps_are_explicit_not_invented(self, terminology):
        rows = terminology.accessions_for("pollinium")
        assert rows and all(row.status == "extension_required" for row in rows)
        assert all(row.accession is None for row in rows)
        # Pseudobulb's only PO candidate (corm) is rejected, never reused.
        pseudo = terminology.accessions_for("pseudobulb")
        assert all(not row.is_usable for row in pseudo)

    def test_entry_payload_matches_lexicon_facade_shape(self, terminology):
        payload = terminology.entry_payload("labellum")
        assert payload["slug"] == "labellum"
        assert payload["preferred_term"] == "Labellum"
        assert payload["review_state"] == "approved"
        assert payload["expanded_definition"]
        assert any(row["accession"] == "FLOPO:0980978" for row in payload["external_accessions"])
        assert "PR #230" in payload["provenance"]["accession_source"]


# ---------------------------------------------------------------------------
# Step 4 — morphological character extraction
# ---------------------------------------------------------------------------


class TestExtraction:
    def test_slipper_orchid(self):
        records = _records("cypripedium_calceolus.txt", CYPRIPEDIUM)
        assert records["habit"].value == "terrestrial"
        assert records["labellum_form"].value == "saccate-pouch"
        assert records["spur_presence"].state_kind == StateKind.ABSENT
        assert records["pollinia_count"].value == 4
        assert records["fragrance"].value == "present"
        assert records["flowering_period"].value == "May to July"
        assert records["resupination"].value == "present"

    def test_epiphyte_with_pseudobulbs(self):
        records = _records("cattleya_labiata.txt", CATTLEYA)
        assert records["habit"].value == "epiphytic"
        assert records["pseudobulb_presence"].value == "present"
        assert records["labellum_form"].value == "3-lobed"
        assert records["pollinia_count"].value == 4
        assert records["leaf_shape"].value == "oblong"

    def test_monopodial_orchid_with_spur_range(self):
        records = _records("vanda_coerulea.txt", VANDA)
        assert records["growth_form"].value == "monopodial"
        assert records["spur_presence"].value == "present"
        assert records["spur_length_mm"].value == {"min": 5.0, "max": 7.0}
        assert records["spur_length_mm"].unit_normalized == "mm"
        assert records["spur_length_mm"].value_normalized == {"min": 5.0, "max": 7.0}
        assert records["pollinia_count"].value == 2
        assert records["leaf_shape"].value == "strap-shaped"

    def test_reduced_mycoheterotroph(self):
        records = _records("rhizanthella_gardneri.txt", RHIZANTHELLA)
        assert records["habit"].value == "subterranean"
        assert records["leaf_presence"].state_kind == StateKind.ABSENT
        assert records["labellum_form"].value == "reduced"
        assert records["resupination"].state_kind == StateKind.ABSENT

    def test_absent_unknown_inapplicable_are_distinct(self):
        vanda = _records("vanda_coerulea.txt", VANDA)
        # Explicit negation in the source -> ABSENT.
        assert vanda["pseudobulb_presence"].state_kind == StateKind.ABSENT
        # Never mentioned -> UNKNOWN (not silently absent).
        assert vanda["fragrance"].state_kind == StateKind.UNKNOWN
        cypripedium = _records("cypripedium_calceolus.txt", CYPRIPEDIUM)
        # Spur is explicitly absent -> spur length cannot apply -> INAPPLICABLE.
        assert cypripedium["spur_length_mm"].state_kind == StateKind.INAPPLICABLE
        rhiz = _records("rhizanthella_gardneri.txt", RHIZANTHELLA)
        # Leafless -> leaf shape INAPPLICABLE, not unknown.
        assert rhiz["leaf_shape"].state_kind == StateKind.INAPPLICABLE

    def test_spans_reference_source_body_exactly(self):
        parsed = _parse("vanda_coerulea.txt")
        records = extract_characters(parsed, VANDA)
        for record in records:
            if record.span is not None:
                assert parsed.body[record.span.start : record.span.end] == record.span.excerpt

    def test_every_record_carries_fixture_provenance(self):
        parsed = _parse("cattleya_labiata.txt")
        for record in extract_characters(parsed, CATTLEYA):
            assert record.source.source_type == "synthetic_test_fixture"
            assert record.provenance_method == "rule_extracted"
            assert record.review_status == "unreviewed"
            assert record.evidence_kind == "literature"


# ---------------------------------------------------------------------------
# Step 5 — evidence store: provenance and contradiction tracking
# ---------------------------------------------------------------------------


class TestEvidenceStore:
    def _store_with_cattleya_conflict(self) -> CharacterEvidenceStore:
        store = CharacterEvidenceStore()
        store.add(extract_characters(_parse("cattleya_labiata.txt"), CATTLEYA))
        store.add(extract_characters(_parse("cattleya_labiata_conflicting_note.txt"), CATTLEYA))
        return store

    def test_contradictory_sources_stay_visible(self):
        store = self._store_with_cattleya_conflict()
        view = store.view(CATTLEYA, "pollinia_count")
        assert view.state_kind == StateKind.CONTRADICTORY
        values = {item["value"] for item in view.disagreement}
        assert values == {4, 8}
        assert len(view.records) == 2  # neither report is dropped or preferred

    def test_agreeing_sources_do_not_conflict(self):
        store = self._store_with_cattleya_conflict()
        view = store.view(CATTLEYA, "labellum_form")
        assert view.state_kind == StateKind.PRESENT
        assert view.value == "3-lobed"

    def test_missing_character_is_unknown_not_absent(self):
        store = CharacterEvidenceStore()
        store.add(extract_characters(_parse("vanda_coerulea.txt"), VANDA))
        view = store.view(VANDA, "fragrance")
        assert view.state_kind == StateKind.UNKNOWN
        assert view.value is None


# ---------------------------------------------------------------------------
# Step 7 — Matrix retrieval and comparison
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def workflow_result(tmp_path_factory):
    root = tmp_path_factory.mktemp("matrix-registry")
    return run_workflow(
        DESCRIPTIONS,
        FIXTURES,
        registry_root=root,
        registry_id="scientific-workflow-test",
        registry_version="1",
        identify_for=[VANDA, CYPRIPEDIUM],
    )


class TestMatrix:
    def test_contradictory_characters_excluded_from_candidates(self, workflow_result):
        store = workflow_result.store
        candidates = {c.taxon_id: c for c in candidates_from_evidence(store, CHARACTERS)}
        cattleya = candidates[CATTLEYA]
        assert "pollinia_count" not in cattleya.states
        excluded = {item["character_id"] for item in cattleya.provenance["excluded_characters"]}
        assert "pollinia_count" in excluded

    def test_unknown_never_becomes_candidate_state(self, workflow_result):
        candidates = {c.taxon_id: c for c in candidates_from_evidence(workflow_result.store, CHARACTERS)}
        assert "fragrance" not in candidates[VANDA].states
        assert "leaf_shape" not in candidates[RHIZANTHELLA].states
        assert "spur_length_mm" not in candidates[CYPRIPEDIUM].states

    def test_registry_version_is_immutable_and_content_addressed(self, workflow_result):
        receipt = workflow_result.registry_receipt
        assert receipt["record"]["checksum_sha256"]
        assert receipt["record"]["publication_state"] == "review_required"
        characters = {item["character"] for item in receipt["record"]["characters"]}
        assert characters == {definition.character_id for definition in CHARACTERS}
        # Registry characters carry lexicon/OAO linkage in provenance.
        labellum = next(
            item for item in receipt["record"]["characters"] if item["character"] == "labellum_form"
        )
        assert labellum["provenance"]["lexicon_term_id"] == "labellum"
        assert labellum["provenance"]["oao_entity_key"] == "labellum"

    def test_vanda_identification_ranks_vanda_first(self, workflow_result):
        result = workflow_result.identifications[VANDA]
        assert result["candidates"][0]["taxon_id"] == VANDA
        assert result["candidates"][0]["score"] == pytest.approx(1.0)
        assert "not a taxonomic determination" in result["disclaimer"]

    def test_cypripedium_identification_prefers_pouch_labellum(self, workflow_result):
        result = workflow_result.identifications[CYPRIPEDIUM]
        assert result["candidates"][0]["taxon_id"] == CYPRIPEDIUM
        explanations = result["candidates"][0]["explanations"]
        labellum = next(item for item in explanations if item["character"] == "labellum_form")
        assert labellum["status"] == "matched"

    def test_unreviewed_extractions_rank_below_certain(self, workflow_result):
        views = workflow_result.store.views_for_taxon(VANDA, [d.character_id for d in CHARACTERS])
        observations = observations_from_views(views, CHARACTERS)
        assert observations
        assert all(obs.certainty in {"probable", "unknown"} for obs in observations)


# ---------------------------------------------------------------------------
# Step 6 — Species Dossier assembly
# ---------------------------------------------------------------------------


class TestDossier:
    def test_dossier_envelope_validates_and_serialises(self, workflow_result):
        payload = workflow_result.dossier_payload(CATTLEYA)
        assert payload["contract_version"] == "oc-species-dossier-v1"
        json.dumps(payload)  # must be JSON-serialisable

    def test_morphology_items_carry_receipts_and_excerpts(self, workflow_result):
        dossier = workflow_result.dossiers[CATTLEYA]
        assert dossier.morphology.state.value == "provisional"
        labellum = next(
            item for item in dossier.morphology.items if item["character_id"] == "labellum_form"
        )
        assert labellum["value"] == "3-lobed"
        assert labellum["excerpts"]
        assert dossier.morphology.receipts
        for receipt in dossier.morphology.receipts:
            assert "synthetic_test_fixture" in (receipt.notes or "")
            assert receipt.evidence_state.value == "provisional"

    def test_contradiction_visible_in_dossier(self, workflow_result):
        dossier = workflow_result.dossiers[CATTLEYA]
        pollinia = next(
            item for item in dossier.morphology.items if item["character_id"] == "pollinia_count"
        )
        assert pollinia["state_kind"] == "contradictory"
        assert {row["value"] for row in pollinia["disagreement"]} == {4, 8}

    def test_missing_sections_are_explicit_not_fabricated(self, workflow_result):
        dossier = workflow_result.dossiers[RHIZANTHELLA]
        assert dossier.pollinators.state.value == "unavailable"
        assert dossier.pollinators.unavailable_reason
        assert dossier.distribution.state.value == "unavailable"
        assert "protected" in dossier.distribution.unavailable_reason
        assert "distribution" in dossier.unavailable_sections

    def test_research_gaps_list_unreported_characters(self, workflow_result):
        dossier = workflow_result.dossiers[VANDA]
        gaps = {item["character_id"] for item in dossier.research_gaps.items}
        assert "fragrance" in gaps

    def test_phenology_and_ecology_from_extraction(self, workflow_result):
        dossier = workflow_result.dossiers[CYPRIPEDIUM]
        assert dossier.phenology.state.value == "provisional"
        assert "May to July" in dossier.phenology.summary
        assert dossier.ecology.items[0]["habit"] == "terrestrial"

    def test_identity_uses_resolved_taxon(self, workflow_result):
        dossier = workflow_result.dossiers[VANDA]
        assert dossier.identity.accepted_name == "Vanda coerulea"
        assert dossier.identity.authorship == "Griff. ex Lindl."
        assert dossier.identity.genus == "Vanda"
        assert "origin=species-dossier" in dossier.matrix_url


# ---------------------------------------------------------------------------
# Step 8 — Illustrated Glossary
# ---------------------------------------------------------------------------


class TestGlossary:
    def test_entry_without_image_says_needs_illustration(self, terminology):
        registry = IllustrationRegistry(FIXTURES.illustrations_csv)
        entry = build_glossary_entry("labellum", terminology, registry)
        assert entry["illustration"]["needs_illustration"] is True
        assert entry["illustration"]["asset_ref"] is None
        assert entry["illustration"]["fabricated"] is False

    def test_existing_schematic_is_class_d_not_specimen(self, terminology):
        registry = IllustrationRegistry(FIXTURES.illustrations_csv)
        entry = build_glossary_entry("resupination", terminology, registry)
        illustration = entry["illustration"]
        assert illustration["status"] == "available"
        assert illustration["illustration_class"] == "D_conceptual_diagram"
        assert illustration["specimen_evidence"] is False
        assert "Famous" in illustration["attribution"]

    def test_glossary_entry_cross_links_matrix_and_dossiers(self, terminology):
        registry = IllustrationRegistry(FIXTURES.illustrations_csv)
        entry = build_glossary_entry(
            "labellum", terminology, registry, matrix_character_ids=["labellum_form"]
        )
        assert entry["cross_links"]["matrix_characters"] == ["labellum_form"]
        assert entry["cross_links"]["species_dossiers"]

    def test_unknown_term_gets_no_fabricated_entry(self, terminology):
        registry = IllustrationRegistry(FIXTURES.illustrations_csv)
        assert build_glossary_entry("does-not-exist", terminology, registry) is None

    def test_workflow_glossary_index_coverage(self, workflow_result):
        coverage = workflow_result.glossary["index"]["illustration_coverage"]
        assert coverage["available"] == 1  # only the resupination schematic
        assert coverage["needs_illustration"] >= 10
        pollinium = workflow_result.glossary["entries"]["pollinium"]
        assert pollinium["illustration"]["needs_illustration"] is True
        assert pollinium["external_accessions"][0]["status"] == "extension_required"


# ---------------------------------------------------------------------------
# Knowledge Graph slice
# ---------------------------------------------------------------------------


class TestKnowledgeGraph:
    def test_graph_links_taxon_character_term_source(self, workflow_result):
        graph = workflow_result.graph
        taxa = graph.nodes_of_type("taxon")
        assert len(taxa) == 4
        characters = graph.nodes_of_type("matrix_character")
        assert len(characters) == len(CHARACTERS)
        terms = graph.nodes_of_type("lexicon_term")
        assert terms
        labellum_node = next(node for node in characters if node.canonical_key == "character:labellum_form")
        neighbours = {node.node_type for _, node in graph.neighbors(labellum_node.kg_node_id)}
        assert {"lexicon_term", "taxon", "evidence_source"} <= neighbours

    def test_graph_edges_keep_provenance(self, workflow_result):
        graph = workflow_result.graph
        exhibits = [edge for edge in graph.edges if edge.edge_type == "taxon_exhibits_character"]
        assert exhibits
        for edge in exhibits:
            assert edge.payload["provenance_method"] == "rule_extracted"
            assert edge.payload["review_status"] == "unreviewed"
            assert edge.confidence_score is not None

    def test_graph_deterministic(self, workflow_result):
        store = workflow_result.store
        terminology = CuratedTerminologyService(
            FIXTURES.lexicon_terms_csv, FIXTURES.oao_accessions_csv
        )
        again = build_graph_slice(store, workflow_result.taxa.values(), terminology)
        assert {node.kg_node_id for node in again.nodes.values()} == {
            node.kg_node_id for node in workflow_result.graph.nodes.values()
        }
        assert {edge.kg_edge_id for edge in again.edges} == {
            edge.kg_edge_id for edge in workflow_result.graph.edges
        }


# ---------------------------------------------------------------------------
# Literature pipeline integration (existing Extractor contract)
# ---------------------------------------------------------------------------


class TestLiteraturePipelineIntegration:
    @pytest.mark.asyncio
    async def test_morphology_extractor_runs_inside_existing_pipeline(self, tmp_path):
        registry = ExtractorRegistry([*DEFAULT_REGISTRY.ordered(), MorphologyExtractor()])
        config = PipelineConfig(
            extractor_settings={
                "morphology": {
                    "taxon_id": VANDA,
                    "taxon_name": "Vanda coerulea Griff. ex Lindl.",
                }
            }
        )
        repository = LiteratureResultRepository(tmp_path / "results")
        source = FIXTURES.root / "pipeline" / "vanda_coerulea_treatment.txt"
        paper = await extract_and_persist(
            source,
            repository,
            registry=registry,
            config=config,
        )
        run = next(item for item in paper.analysis_manifest.extractors if item.name == "morphology")
        assert run.status == "completed"
        morphology_claims = [
            claim for claim in paper.claims if claim.provenance.extractor == "scientific-workflow-morphology"
        ]
        assert morphology_claims
        assert all(claim.provenance.method == "rule_extracted" for claim in morphology_claims)
        assert all(claim.provenance.review_status == "unreviewed" for claim in morphology_claims)
        assert any(claim.predicate == "pollinia_count" for claim in morphology_claims)
        measurements = [
            item for item in paper.measurements if item.property == "spur_length_mm"
        ]
        assert measurements and measurements[0].unit == "mm"
        # Every claim has evidence, and every evidence span validates against
        # the raw source text (pipeline-level invariant).
        raw = source.read_text(encoding="utf-8")
        evidence_by_id = {item.evidence_id: item for item in paper.evidence}
        for claim in morphology_claims:
            assert claim.evidence_ids
            for evidence_id in claim.evidence_ids:
                evidence = evidence_by_id[evidence_id]
                assert raw[evidence.span.char_start : evidence.span.char_end] == evidence.excerpt

    @pytest.mark.asyncio
    async def test_extractor_refuses_unresolved_taxon(self, tmp_path):
        extractor = MorphologyExtractor()
        from app.literature_extraction.context import PipelineContext
        from app.literature_extraction.ingest import build_empty_paper, ingest_text

        source = FIXTURES.root / "pipeline" / "vanda_coerulea_treatment.txt"
        document = ingest_text(source)
        paper = build_empty_paper(document, pipeline_version="0.2.0")
        context = PipelineContext(source_path=source, output_dir=tmp_path, config=PipelineConfig())
        _, run = await extractor.execute(context, paper)
        assert run.status == "failed"
        assert "taxon_id" in (run.error or "")

    @pytest.mark.asyncio
    async def test_front_matter_spans_reprojected_to_raw_document(self, tmp_path):
        """Front matter must not break the raw-span invariant.

        Regression test: evidence spans are captured relative to the
        description body, but the literature pipeline validates them against
        the full raw document (``raw[char_start:char_end] == excerpt``), so
        the extractor must re-project them by the front-matter offset.
        """
        from app.literature_extraction.context import PipelineContext
        from app.literature_extraction.ingest import build_empty_paper, ingest_text

        source = tmp_path / "front_matter_treatment.txt"
        source.write_text(
            "---\n"
            "fixture_id: front-matter-regression\n"
            "taxon_name: Vanda coerulea\n"
            "source_type: test_fixture\n"
            "rights_status: synthetic_test_fixture\n"
            "attribution: Orchid Continuum synthetic test fixture\n"
            "---\n"
            "Vanda coerulea is a monopodial epiphyte. Pollinia 4. Spur slender, 12-15 mm.\n",
            encoding="utf-8",
        )
        extractor = MorphologyExtractor()
        document = ingest_text(source)
        paper = build_empty_paper(document, pipeline_version="0.2.0")
        context = PipelineContext(
            source_path=source,
            output_dir=tmp_path,
            config=PipelineConfig(
                extractor_settings={
                    "morphology": {
                        "taxon_id": VANDA,
                        "taxon_name": "Vanda coerulea Griff. ex Lindl.",
                    }
                }
            ),
        )
        paper, run = await extractor.execute(context, paper)
        assert run.status == "completed"
        raw = source.read_text(encoding="utf-8")
        morphology_evidence = [
            item for item in paper.evidence if item.evidence_id.startswith("ev-obs-")
        ]
        assert morphology_evidence
        for item in morphology_evidence:
            assert raw[item.span.char_start : item.span.char_end] == item.excerpt
