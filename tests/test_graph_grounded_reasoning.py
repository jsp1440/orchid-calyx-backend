import ast
import json
from dataclasses import replace
from pathlib import Path

import pytest

from app.calyx_flywheel.locality import assert_no_sensitive_locality
from app.graph_grounded_reasoning import (
    Facet,
    GraphGroundedReasoner,
    ResultState,
    ScientificQuestion,
)
from app.graph_grounded_reasoning.benchmark import (
    BASELINE_ID,
    build_environment,
    fixture_taxon_node_key,
    load_json,
    run_benchmark,
)
from app.graph_grounded_reasoning.contracts import (
    CONTRACT_VERSION,
    MAX_EVIDENCE_RECORDS,
    MAX_GRAPH_RECORDS,
    Claim,
    Composition,
)
from app.graph_grounded_reasoning.reasoning import compose
from app.graph_grounded_reasoning.retrieval import ReadOnlyGraphView
from runtime.knowledge_graph.claim_provenance import (
    ClaimProvenance,
    SourceAnchor,
    TaxonBinding,
)
from runtime.knowledge_graph.models import Edge, Node
from runtime.knowledge_graph.repository import InMemoryGraphRepository


def environment():
    return build_environment(load_json("fixture.json"))


def node_key(registry):
    return fixture_taxon_node_key(load_json("fixture.json"), registry)


def reasoner(**kwargs):
    registry, graph, engine = environment()
    kwargs.setdefault("search", engine.search)
    return GraphGroundedReasoner(registry, graph, node_key(registry), **kwargs)


def ask(text, facet, **kwargs):
    return reasoner(**kwargs).answer(ScientificQuestion(text, facet))


def provenance(assertion_id, document_id, *, taxon="Exemplaria aurea", node_key="taxon:1", **overrides):
    record = ClaimProvenance(
        source_document_id=document_id,
        source_revision_id=overrides.pop("revision", None),
        content_hash=overrides.pop("content_hash", None),
        anchors=(SourceAnchor(page_start=1, page_end=1),),
        taxon=TaxonBinding(taxon, "accepted", "fixture-release", node_key),
        extraction_method="human_annotated",
        review_status=overrides.pop("review_status", "accepted"),
        assertion_id=assertion_id,
        confidence=0.9,
        **overrides,
    )
    return {"claim_provenance": record.to_payload()}


class SpyGraph(InMemoryGraphRepository):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.reads = 0
        self.writes = 0

    def get_node_by_key(self, key):
        self.reads += 1
        return super().get_node_by_key(key)

    def upsert_node(self, node):
        self.writes += 1
        return super().upsert_node(node)

    def upsert_edge(self, edge):
        self.writes += 1
        return super().upsert_edge(edge)


def test_question_contract_rejects_empty_oversized_and_unknown_facet():
    assert ScientificQuestion("  Which   pollinators? ", "POLLINATION").text == "Which pollinators?"
    for text, facet in (("", "POLLINATION"), ("x" * 501, "POLLINATION"), ("ok", "WEATHER")):
        with pytest.raises(ValueError):
            ScientificQuestion(text, facet)


def test_synonym_resolves_to_accepted_taxon_and_records_the_hop():
    result = ask("Which pollinators are recorded for Fictorchis aurea?", Facet.POLLINATION)
    resolution = result["resolution"]
    assert resolution["state"] == "RESOLVED_VIA_SYNONYM"
    assert resolution["via_synonym"] == "Fictorchis aurea"
    assert resolution["accepted_name"] == "Exemplaria aurea"
    assert resolution["authority"] == "world_plants"
    assert any(u.startswith("SYNONYM_RESOLVED:Fictorchis aurea") for u in result["uncertainty"])
    assert all(c["subject_canonical_id"] == resolution["accepted_canonical_id"] for c in result["claims"])


def test_conflicting_assertions_are_both_retained_and_never_merged():
    result = ask("Which pollinators visit Exemplaria aurea?", Facet.POLLINATION)
    assert result["state"] == ResultState.CONFLICT_REVIEW_REQUIRED
    assert result["conflicts"] == [["kg_edge:102", "kg_edge:103"]]
    cited = sorted(ref for claim in result["claims"] for ref in claim["refs"])
    assert cited == ["kg_edge:102", "kg_edge:103"]
    assert {c["document_id"] for c in result["citations"].values()} == {"doc-pol-1", "doc-pol-2"}
    assert result["validation"]["passed"]


def test_every_citation_resolves_to_revision_anchor_and_content_hash():
    result = ask("Which mycorrhizal fungi associate with Exemplaria rubra?", Facet.MYCORRHIZA)
    assert result["state"] == ResultState.CANDIDATE
    [citation] = result["citations"].values()
    assert citation["document_id"] == "doc-myc-2"
    assert citation["revision_id"] == "doc-myc-2@r1"
    assert citation["source_anchor_ids"] and isinstance(citation["locator"], dict)
    assert len(citation["source_content_hash"]) == 64


@pytest.mark.parametrize(
    "text,facet,gap",
    [
        ("Which pollinators visit Exemplaria nivea?", Facet.POLLINATION, "NO_GRAPH_EVIDENCE_FOR_FACET:POLLINATION"),
        ("Which mycorrhizal fungi associate with Exemplaria aurea?", Facet.MYCORRHIZA, "NO_ANCHORED_SOURCE_FOR_FACET"),
        ("What is the labellum colour of Exemplaria rubra?", Facet.MORPHOLOGY, "NO_ANCHORED_SOURCE_FOR_FACET"),
        ("Where does Exemplaria obscura occur?", Facet.DISTRIBUTION, "TAXON_GRAPH_LINK_UNVERIFIED"),
    ],
)
def test_insufficient_evidence_is_an_explicit_abstention(text, facet, gap):
    result = ask(text, facet)
    assert result["state"] == ResultState.INSUFFICIENT_EVIDENCE
    assert result["claims"] == [] and result["citations"] == {}
    assert gap in result["gaps"]
    assert result["validation"]["passed"]


def test_focal_node_must_carry_the_accepted_name_or_nothing_is_read():
    registry, graph, engine = environment()
    wrong_node = GraphGroundedReasoner(registry, graph, lambda _: "taxon:2", search=engine.search)
    result = wrong_node.answer(
        ScientificQuestion("Which pollinators visit Exemplaria aurea?", Facet.POLLINATION)
    )
    assert result["state"] == ResultState.INSUFFICIENT_EVIDENCE
    assert "FOCAL_NODE_IDENTITY_MISMATCH" in result["gaps"]
    assert result["evidence_packet"]["items"] == []


def test_unanchored_assertion_is_reported_but_not_cited():
    result = ask("Which mycorrhizal fungi associate with Exemplaria aurea?", Facet.MYCORRHIZA)
    [item] = [i for i in result["evidence_packet"]["items"] if i["domain"] == "mycorrhiza"]
    assert item["anchor_state"] == "SOURCE_UNDECLARED"


@pytest.mark.parametrize(
    "text,state",
    [
        ("Which pollinators visit Imaginaria fabulosa?", "UNRESOLVED"),
        ("Do Exemplaria aurea and Exemplaria rubra share pollinators?", "AMBIGUOUS"),
    ],
)
def test_unresolved_or_ambiguous_taxon_never_guesses_and_never_reads_graph(text, state):
    registry, graph, engine = environment()
    spy = SpyGraph(graph.all_nodes(), graph.all_edges())
    result = GraphGroundedReasoner(registry, spy, node_key(registry), search=engine.search).answer(
        ScientificQuestion(text, Facet.POLLINATION)
    )
    assert result["resolution"]["state"] == state
    assert result["resolution"]["accepted_canonical_id"] is None
    assert result["state"] == ResultState.INSUFFICIENT_EVIDENCE
    assert f"TAXON_{state}" in result["gaps"]
    assert spy.reads == 0


def test_mixed_review_states_require_review_and_do_not_claim_candidate():
    result = ask("What floral traits distinguish Exemplaria aurea?", Facet.MORPHOLOGY)
    assert result["state"] == ResultState.REVIEW_REQUIRED
    assert "UNREVIEWED_OR_UNVERIFIED_ASSERTIONS:1" in result["uncertainty"]


def test_sensitive_locality_is_withheld_and_no_coordinate_key_escapes():
    result = ask("Where does Exemplaria aurea occur?", Facet.DISTRIBUTION)
    assert result["state"] == ResultState.CANDIDATE
    assert result["evidence_packet"]["withheld_count"] == 1
    assert "SENSITIVE_RECORDS_WITHHELD" in result["gaps"]
    assert_no_sensitive_locality(result)
    assert "withheld test locality" not in json.dumps(result)


def test_graph_reads_are_bounded_and_truncation_is_reported():
    registry, _, engine = environment()
    focal = Node(1, "taxon", "taxon:1", "Exemplaria aurea")
    nodes = [focal] + [Node(1000 + i, "trait", f"trait:{i}", f"trait {i}") for i in range(40)]
    edges = [
        Edge(5000 + i, "has_trait", 1, 1000 + i, payload=provenance(f"a-{i}", f"doc-x-{i}"))
        for i in range(40)
    ]
    calls = []

    def search(query):
        calls.append(query)
        return engine.search(query)

    result = GraphGroundedReasoner(
        registry, InMemoryGraphRepository(nodes, edges), lambda _: "taxon:1", search=search
    ).answer(
        ScientificQuestion("What traits does Exemplaria aurea have?", Facet.MORPHOLOGY)
    )
    packet = result["evidence_packet"]
    assert len(packet["items"]) == MAX_GRAPH_RECORDS
    assert len(calls) == MAX_EVIDENCE_RECORDS
    assert packet["truncated"] and "RETRIEVAL_LIMIT_REACHED" in packet["gaps"]
    assert packet["limits"]["graph_depth"] == 1


def test_read_only_view_exposes_no_write_path_and_writes_never_happen():
    registry, graph, engine = environment()
    spy = SpyGraph(graph.all_nodes(), graph.all_edges())
    view = ReadOnlyGraphView(spy)
    for name in ("upsert_node", "upsert_edge", "commit", "acquire_publication_lock", "all_edges"):
        assert not hasattr(view, name)
    GraphGroundedReasoner(registry, spy, node_key(registry), search=engine.search).answer(
        ScientificQuestion("Which pollinators visit Exemplaria aurea?", Facet.POLLINATION)
    )
    assert spy.reads == 1 and spy.writes == 0


def test_package_has_no_write_provider_or_generated_query_surface():
    attributes, imports, strings = set(), set(), []
    for path in Path("app/graph_grounded_reasoning").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Attribute):
                attributes.add(node.attr)
            elif isinstance(node, ast.Import):
                imports |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".")[0])
                imports |= {a.name for a in node.names}
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                strings.append(node.value.upper())
    assert not attributes & {
        "upsert_node", "upsert_edge", "commit", "execute", "cursor",
        "acquire_publication_lock",
    }
    assert not imports & {
        "openai", "anthropic", "requests", "httpx", "psycopg", "psycopg2",
        "sqlalchemy", "neo4j", "WritablePostgresGraphRepository",
    }
    for fragment in ("INSERT INTO", "UPDATE OC_", "DELETE FROM", "MATCH ("):
        assert not any(fragment in value for value in strings), fragment


def test_answers_are_deterministic_apart_from_timings():
    first = ask("Which pollinators visit Exemplaria aurea?", Facet.POLLINATION)
    second = ask("Which pollinators visit Exemplaria aurea?", Facet.POLLINATION)
    first.pop("timings_ms"), second.pop("timings_ms")
    assert first == second
    assert first["contract_version"] == CONTRACT_VERSION
    assert first["governance"]["provider_calls"] == 0
    assert first["governance"]["published"] is False


def _hallucinating(packet):
    return Composition(
        state=ResultState.CANDIDATE,
        claims=(Claim("Exemplaria aurea is pollinated by moths", packet.resolution.accepted_canonical_id, ("kg_edge:999",)),),
        conflicts=(),
        uncertainty=(),
        gaps=(),
    )


def _drops_conflict(packet):
    honest = compose(packet)
    return replace(honest, state=ResultState.CANDIDATE, conflicts=())


def _answers_without_evidence(packet):
    return Composition(
        state=ResultState.CANDIDATE,
        claims=(Claim("plausible general knowledge", packet.resolution.accepted_canonical_id, ()),),
        conflicts=(),
        uncertainty=(),
        gaps=(),
    )


def _wrong_subject(packet):
    honest = compose(packet)
    return replace(honest, claims=tuple(replace(c, subject_canonical_id=2) for c in honest.claims))


@pytest.mark.parametrize(
    "composer,text,violation",
    [
        (_hallucinating, "Which pollinators visit Exemplaria rubra?", "CLAIM_0_CITES_UNKNOWN_REF:kg_edge:999"),
        (_drops_conflict, "Which pollinators visit Exemplaria aurea?", "DECLARED_CONFLICT_DROPPED"),
        (_answers_without_evidence, "Which pollinators visit Exemplaria nivea?", "ANSWERED_WITHOUT_ANCHORED_EVIDENCE"),
        (_wrong_subject, "Which pollinators visit Exemplaria aurea?", "CLAIM_0_SUBJECT_NOT_CANONICAL_TAXON"),
    ],
)
def test_validator_fails_closed_on_any_composer_including_future_model_ones(composer, text, violation):
    result = ask(text, Facet.POLLINATION, composer=composer)
    assert result["state"] == ResultState.VALIDATION_FAILED
    assert result["claims"] == [] and result["citations"] == {}
    assert violation in result["validation"]["violations"]
    assert result["governance"]["provider_calls"] is None


def test_benchmark_is_reproducible_labelled_and_compares_identical_cases():
    first, second = run_benchmark(), run_benchmark()
    assert first["label_source"] == "FIXTURE_CONSTRUCTION"
    assert first["expert_reviewed"] is False
    assert first["fixture_sha256"] == second["fixture_sha256"]
    assert set(first["systems"]) == {BASELINE_ID, CONTRACT_VERSION}
    def strip(rows):
        return [{k: v for k, v in r.items() if k != "latency_ms"} for r in rows]

    for name in first["systems"]:
        assert strip(first["systems"][name]["cases"]) == strip(second["systems"][name]["cases"])
        assert first["systems"][name]["summary"]["provider_calls"] == 0
    case_ids = [[r["case_id"] for r in s["cases"]] for s in first["systems"].values()]
    assert case_ids[0] == case_ids[1]
    categories = {r["category"] for r in first["systems"][CONTRACT_VERSION]["cases"]}
    assert categories == {
        "taxonomy_synonymy",
        "morphological_identification",
        "species_description",
        "pollination_biology",
        "mycorrhizal_associations",
        "geographic_distribution",
        "conflicting_literature",
        "uncertain_incomplete",
    }
    grounded = first["systems"][CONTRACT_VERSION]["summary"]
    assert grounded["unsupported_citation_count"] == 0
    assert grounded["conflict_retention_rate"] == 1.0
    assert grounded["abstention_recall"] == 1.0


# --- review findings (#1819): each guard below is exercised directly ---------


def test_question_words_are_not_taxon_mentions_and_unknown_mentions_abstain():
    from app.graph_grounded_reasoning.resolution import mentioned_names

    assert mentioned_names("Which pollinators visit Exemplaria aurea?") == ("Exemplaria aurea",)
    result = ask("Do Exemplaria aurea and Imaginaria fabulosa share pollinators?", Facet.POLLINATION)
    assert result["resolution"]["state"] == "AMBIGUOUS"
    assert result["state"] == ResultState.INSUFFICIENT_EVIDENCE and result["claims"] == []


def test_anchor_requires_a_non_empty_locator_and_a_content_hash():
    registry, graph, engine = environment()

    def no_hash(query):
        result = engine.search(query)
        for row in result["results"]:
            row["source_content_hash"] = None
        return result

    def short_hash(query):
        result = engine.search(query)
        for row in result["results"]:
            row["source_content_hash"] = "abc123"
        return result

    def empty_locator(query):
        result = engine.search(query)
        for row in result["results"]:
            row["citation"]["locator"] = {}
        return result

    for search in (no_hash, short_hash, empty_locator):
        result = GraphGroundedReasoner(registry, graph, node_key(registry), search=search).answer(
            ScientificQuestion("Which mycorrhizal fungi associate with Exemplaria rubra?", Facet.MYCORRHIZA)
        )
        assert result["state"] == ResultState.INSUFFICIENT_EVIDENCE
        assert {i["anchor_state"] for i in result["evidence_packet"]["items"]} == {"ANCHOR_UNAVAILABLE"}


def test_unrelated_edges_cannot_crowd_facet_evidence_out_of_the_bound():
    registry, graph, engine = environment()
    nodes = graph.all_nodes() + [Node(7000 + i, "image", f"image:{i}", f"image {i}") for i in range(30)]
    # Thirty low-id media edges ahead of the real pollination edges.
    edges = [Edge(i + 1, "has_image", 1, 7000 + i) for i in range(30)] + graph.all_edges()
    result = GraphGroundedReasoner(
        registry, InMemoryGraphRepository(nodes, edges), node_key(registry), search=engine.search
    ).answer(ScientificQuestion("Which pollinators visit Exemplaria aurea?", Facet.POLLINATION))
    assert result["state"] == ResultState.CONFLICT_REVIEW_REQUIRED
    assert result["evidence_packet"]["truncated"] is False


def _drops_one_conflict_claim(packet):
    honest = compose(packet)
    return replace(honest, claims=honest.claims[:1])


def _invents_conflict(packet):
    honest = compose(packet)
    return replace(honest, conflicts=honest.conflicts + (("kg_edge:1", "kg_edge:2"),))


def _promotes_unreviewed(packet):
    return replace(compose(packet), state=ResultState.CANDIDATE)


def _leaks_locality(packet):
    honest = compose(packet)
    claim = honest.claims[0]
    leaky = Claim(claim.statement, claim.subject_canonical_id, claim.refs)
    object.__setattr__(leaky, "to_dict", lambda: {**claim.to_dict(), "verbatimLocality": "x"})
    return replace(honest, claims=(leaky,))


@pytest.mark.parametrize(
    "composer,text,facet,violation",
    [
        (_drops_one_conflict_claim, "Which pollinators visit Exemplaria aurea?", Facet.POLLINATION,
         "CONFLICT_ENDPOINT_NOT_CITED:kg_edge:103"),
        (_invents_conflict, "Which pollinators visit Exemplaria aurea?", Facet.POLLINATION,
         "UNDECLARED_CONFLICT_ASSERTED"),
        (_promotes_unreviewed, "What floral traits distinguish Exemplaria aurea?", Facet.MORPHOLOGY,
         "CANDIDATE_WITH_UNREVIEWED_OR_UNANCHORED_EVIDENCE"),
        (_leaks_locality, "Which mycorrhizal fungi associate with Exemplaria rubra?", Facet.MYCORRHIZA,
         "FORBIDDEN_LOCALITY_KEYS:SENSITIVE_LOCALITY_FORBIDDEN: claims[0].verbatimLocality"),
    ],
)
def test_validator_closes_the_review_findings(composer, text, facet, violation):
    result = ask(text, facet, composer=composer)
    assert result["state"] == ResultState.VALIDATION_FAILED
    assert violation in result["validation"]["violations"]
