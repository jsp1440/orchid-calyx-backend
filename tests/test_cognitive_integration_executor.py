"""Proofs for the Cognitive Integration path (backend #1502).

The path runs on the existing knowledge-graph repository protocol and the
existing ``ReasoningMapEngine``. These tests check it *reasons* — selects
capabilities, traverses relationships, finds the contradiction and the gaps in
the data rather than reciting them — and that it does so with no provider and no
locality leak.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.cognitive_integration.executor import (
    DETERMINISTIC_CAPABILITIES,
    OPTIONAL_CAPABILITY,
    CognitiveIntegrationError,
    execute,
)
from app.cognitive_integration.fixture import build_pollination_repository
from app.main import app
from app.provider_reservoir.capabilities import is_provider_capability
from runtime.knowledge_graph import Edge, Node
from runtime.knowledge_graph.repository import InMemoryGraphRepository


@pytest.fixture(scope="module")
def reasoning_map() -> dict:
    return execute()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


# ---------------------------------------------------------------------------
# It runs with no provider, and every capability it uses is deterministic
# ---------------------------------------------------------------------------


def test_the_whole_path_runs_with_no_provider(reasoning_map):
    assert reasoning_map["execution"]["provider_calls"] == 0
    assert reasoning_map["execution"]["explanation_available"] is False
    assert reasoning_map["execution"]["explanation"] is None


def test_every_capability_the_path_uses_is_classified_deterministic():
    """Pinned against the router's own registry, not a local copy of it."""
    for capability in DETERMINISTIC_CAPABILITIES:
        assert is_provider_capability(capability) is False


def test_the_one_optional_capability_is_the_only_provider_one():
    assert is_provider_capability(OPTIONAL_CAPABILITY) is True


def test_optional_explanation_adds_prose_and_changes_nothing_else():
    without = execute()
    with_prose = execute(explanation="The bee orchid is a puzzle: ...")

    assert with_prose["execution"]["explanation_available"] is True
    assert with_prose["execution"]["provider_calls"] == 1
    for key in ("relationships", "mechanisms", "contradictions", "evidence_gaps",
                "known_unknowns", "confidence", "taxonomic_identity"):
        assert with_prose[key] == without[key], f"{key} changed when prose was added"


# ---------------------------------------------------------------------------
# It uses the real engine and the real graph, not a parallel structure
# ---------------------------------------------------------------------------


def test_the_traversal_runs_on_the_real_reasoning_engine(reasoning_map):
    traversal = reasoning_map["execution"]["traversal"]
    assert traversal["engine"] == "app.brain.reasoning_map.ReasoningMapEngine"
    assert traversal["path_count"] > 0
    assert traversal["edge_count"] > 0


def test_the_fixture_is_ordinary_graph_records():
    repo = build_pollination_repository()
    assert isinstance(repo, InMemoryGraphRepository)
    assert repo.get_node_by_key("taxon:ophrys-apifera") is not None
    assert all(isinstance(edge, Edge) for edge in repo.all_edges())


# ---------------------------------------------------------------------------
# It reasons: identity, evidence, contradiction, gaps
# ---------------------------------------------------------------------------


def test_it_resolves_a_taxonomic_identity_and_says_against_what(reasoning_map):
    identity = reasoning_map["taxonomic_identity"]
    assert identity["accepted_name"] == "Ophrys apifera"
    assert identity["authorship"] == "Huds."
    assert identity["resolved_against"]


def test_every_relationship_carries_provenance_and_a_permitted_state(reasoning_map):
    allowed = {"SUPPORTED", "CONTESTED", "REPORTED_UNVERIFIED", "REFUTED"}
    assert reasoning_map["relationships"]
    for relationship in reasoning_map["relationships"]:
        assert relationship["evidence_state"] in allowed
        assert relationship["provenance"]
        assert relationship["provenance"][0]["citation"].strip()


def test_nothing_is_presented_as_canonical_fact(reasoning_map):
    states = {r["evidence_state"] for r in reasoning_map["relationships"]}
    assert "FACT" not in states
    assert reasoning_map["governance"]["automatic_knowledge_promotion"] is False


def test_literature_and_dataset_evidence_are_both_present(reasoning_map):
    kinds = {p["source_type"] for r in reasoning_map["relationships"] for p in r["provenance"]}
    assert "peer_reviewed_literature" in kinds
    assert kinds & {"occurrence_dataset", "interaction_dataset", "human_observation"}


def test_the_contradiction_is_found_in_the_data_not_recited(reasoning_map):
    """Remove one side of the disagreement and the contradiction must disappear."""
    contradictions = reasoning_map["contradictions"]
    assert len(contradictions) == 1
    assert contradictions[0]["resolution"] == "unresolved_presented_as_contested"
    assert set(contradictions[0]["scopes"]) == {
        "predominant throughout the range",
        "sporadically reported, chiefly in the Mediterranean",
    }

    repo = build_pollination_repository()
    remaining = [e for e in repo.all_edges() if e.edge_type != "reported_pollinated_by"]
    reduced = execute(repository=InMemoryGraphRepository(
        nodes=list(repo.all_nodes()), edges=remaining))
    assert reduced["contradictions"] == [], "the contradiction was hardcoded, not derived"


def _with_scope_regions(repo, first_region, second_region):
    """Return the fixture with each reproductive report pinned to a named region."""
    regions = iter((first_region, second_region))
    edges = []
    for edge in repo.all_edges():
        if edge.edge_type in ("reported_pollinated_by", "reported_reproductive_strategy"):
            payload = dict(edge.payload)
            payload["scope_region"] = next(regions)
            edge = Edge(
                kg_edge_id=edge.kg_edge_id, edge_type=edge.edge_type,
                from_node_id=edge.from_node_id, to_node_id=edge.to_node_id,
                evidence_class=edge.evidence_class, payload=payload,
            )
        edges.append(edge)
    return InMemoryGraphRepository(nodes=list(repo.all_nodes()), edges=edges)


def test_two_claims_about_the_same_place_are_never_resolved_by_scope():
    """The rule ran backwards: equal scope strings returned ``resolved_by_scope``.

    Two incompatible claims about the *same* place is the definition of a live
    conflict. The inverted rule dropped it from ``unresolved`` and raised the
    confidence for it, so a graph with a standing contradiction was served at
    ``high`` with the basis "No retrieved report contradicts another."
    """
    repo = build_pollination_repository()
    same_place = execute(
        repository=_with_scope_regions(repo, "region:mediterranean", "region:mediterranean")
    )
    assert same_place["contradictions"][0]["resolution"] == "unresolved_presented_as_contested"
    assert same_place["confidence"]["qualitative"] != "high"
    assert "Reports conflict" in same_place["confidence"]["basis"]


def test_an_unscoped_contradiction_is_never_resolved_by_scope():
    """Absent scope is unknown, not equal, and not disjoint.

    Under string equality two missing scopes compared equal, so *any* pair of
    contradicting claims that named no place — the common case — was reported
    resolved.
    """
    result = execute()  # the shipped fixture carries no structured region
    assert result["contradictions"][0]["resolution"] == "unresolved_presented_as_contested"


def test_differing_free_text_scopes_alone_do_not_resolve_anything():
    """Different wording is not disjointness.

    The fixture's two scopes — "predominant throughout the range" and
    "sporadically reported, chiefly in the Mediterranean" — describe overlapping
    ground. Treating unequal strings as separate places would convert a real
    disagreement into a resolved one.
    """
    result = execute()
    scopes = result["contradictions"][0]["scopes"]
    assert scopes[0] != scopes[1], "the fixture's scopes differ as strings"
    assert result["contradictions"][0]["resolution"] == "unresolved_presented_as_contested"
    notes = " ".join(result["geographic_context"]["environmental_notes"])
    assert "does not divide the range" in notes


def test_scope_resolves_only_when_the_graph_establishes_disjoint_regions():
    """The one case that is genuinely resolved, and it has to be declared.

    Both claims name a region and the graph carries a ``disjoint_from`` edge
    between them, so they do not bear on the same ground.
    """
    repo = build_pollination_repository()
    declared = {
        frozenset({e.from_node_id, e.to_node_id})
        for e in repo.all_edges()
        if e.edge_type == "disjoint_from"
    }
    assert declared, "the fixture must declare at least one disjoint pair"

    resolved = execute(
        repository=_with_scope_regions(
            repo, "region:mediterranean", "region:north-western-europe"
        )
    )
    assert resolved["contradictions"][0]["resolution"] == "resolved_by_scope"
    notes = " ".join(resolved["geographic_context"]["environmental_notes"])
    assert "differs between parts of the range" in notes


def test_undeclared_regions_do_not_resolve_even_when_they_differ():
    """Two region names nothing declares disjoint stay contested."""
    repo = build_pollination_repository()
    result = execute(
        repository=_with_scope_regions(repo, "region:mediterranean", "region:invented-elsewhere")
    )
    assert result["contradictions"][0]["resolution"] == "unresolved_presented_as_contested"


def test_the_evidence_gaps_are_derived_from_what_the_graph_lacks(reasoning_map):
    gaps = " ".join(reasoning_map["evidence_gaps"])
    assert "pollination observation" in gaps
    assert "quantifies" in gaps
    # Derived by noticing the node's own payload, not written into the output.
    assert "genus, not species" in gaps


def test_adding_the_missing_evidence_removes_its_gap():
    repo = build_pollination_repository()
    nodes = list(repo.all_nodes())
    edges = list(repo.all_edges())
    edges.append(Edge(
        kg_edge_id=99, edge_type="observed_pollination_event",
        from_node_id=1, to_node_id=2, evidence_class="SUPPORTED",
        payload={"citation": "Field observation record", "source_type": "human_observation"},
    ))
    enriched = execute(repository=InMemoryGraphRepository(nodes=nodes, edges=edges))
    gaps = " ".join(enriched["evidence_gaps"])
    assert "no population-level pollination observation is held" not in gaps
    assert "No local observation supports any retrieved claim" not in gaps


def test_a_competing_mechanism_and_a_null_explanation_are_both_offered(reasoning_map):
    kinds = {m["kind"] for m in reasoning_map["mechanisms"]}
    assert kinds == {"proposed_mechanism", "competing_mechanism", "null_explanation"}


def test_confidence_is_qualitative_with_a_basis_and_no_invented_number(reasoning_map):
    confidence = reasoning_map["confidence"]
    assert confidence["numeric_precision_claimed"] is False
    assert confidence["qualitative"] in ("low", "moderate", "high")
    assert confidence["basis"].strip()
    assert not any(ch.isdigit() for ch in confidence["qualitative"])


def test_the_confidence_basis_cannot_contradict_the_confidence_value():
    """Value and reasons are derived together, and both follow the served map.

    Computing them in one function stopped them disagreeing with *each other*.
    They could still disagree with the map they were served in, because
    ``unresolved`` was fed by the inverted scope rule: a graph whose
    contradiction was wrongly called resolved reported "No retrieved report
    contradicts another" directly above the contradiction it listed.
    """
    contested = execute()
    assert "Reports conflict" in contested["confidence"]["basis"]
    assert contested["contradictions"], "the basis must describe the served map"

    repo = build_pollination_repository()
    resolved = execute(
        repository=_with_scope_regions(
            repo, "region:mediterranean", "region:north-western-europe"
        )
    )
    assert resolved["confidence"]["qualitative"] != contested["confidence"]["qualitative"]
    assert "Reports conflict" not in resolved["confidence"]["basis"]
    assert "No retrieved report contradicts another" in resolved["confidence"]["basis"]


def test_no_map_claims_agreement_while_serving_a_standing_contradiction():
    """The invariant behind D3, asserted over every scope arrangement.

    Whatever the scopes, a basis saying nothing contradicts must not appear in a
    map that carries an unresolved contradiction.
    """
    repo = build_pollination_repository()
    arrangements = [
        execute(),
        execute(repository=_with_scope_regions(repo, "region:mediterranean", "region:mediterranean")),
        execute(repository=_with_scope_regions(repo, "region:mediterranean", "region:invented")),
        execute(
            repository=_with_scope_regions(
                repo, "region:mediterranean", "region:north-western-europe"
            )
        ),
    ]
    for result in arrangements:
        standing = [
            c
            for c in result["contradictions"]
            if c["resolution"] == "unresolved_presented_as_contested"
        ]
        agrees = "No retrieved report contradicts another" in result["confidence"]["basis"]
        assert not (standing and agrees), result["confidence"]["basis"]
        if standing:
            assert result["confidence"]["qualitative"] != "high"


@pytest.mark.parametrize(
    "leak",
    [
        "Population located at 51.7520 -1.2577 near the reserve",
        "Population at 51.75, -1.25",
        "lat 51.7520 lon -1.2577",
        "Recorded at 43\u00b0 17\u2019 N",
        "51.7520, -1.2577",
    ],
)
def test_every_coordinate_shape_a_checker_found_is_now_caught(leak):
    """Each of these was served verbatim by the first version of the redactor.

    Space-separated pairs are ~10 m precision; two decimal places are ~1 km.
    Both are enough to locate a protected population.
    """
    repo = build_pollination_repository()
    edges = []
    for edge in repo.all_edges():
        payload = dict(edge.payload)
        if edge.edge_type == "co_occurs_with":
            payload["citation"] = leak
        edges.append(Edge(
            kg_edge_id=edge.kg_edge_id, edge_type=edge.edge_type,
            from_node_id=edge.from_node_id, to_node_id=edge.to_node_id,
            evidence_class=edge.evidence_class, payload=payload,
        ))
    served = json.dumps(execute(repository=InMemoryGraphRepository(
        nodes=list(repo.all_nodes()), edges=edges)))
    assert "51.75" not in served
    assert "-1.25" not in served
    assert "locality withheld" in served


def test_ordinary_scientific_text_is_not_redacted():
    from app.cognitive_integration.executor import _redact

    text = "Pollinated by Eulaema meriana; 3 of 7 records confirm the association."
    assert _redact(text) == text


def test_the_fail_closed_check_is_broader_than_the_redactor():
    """A check sharing the redactor's pattern can only confirm what it already did."""
    from app.cognitive_integration.executor import _COORDINATE, _COORDINATE_SUSPICION

    # A bare mention the redactor does not remove, which the suspicion net catches.
    probe = "gps reading withheld"
    assert _COORDINATE.search(probe) is None
    assert _COORDINATE_SUSPICION.search(probe) is not None


def test_known_unknowns_and_next_evidence_are_both_stated(reasoning_map):
    assert len(reasoning_map["known_unknowns"]) >= 3
    assert len(reasoning_map["recommended_next_evidence"]) >= 3


# ---------------------------------------------------------------------------
# Locality, handoffs, governance
# ---------------------------------------------------------------------------


def test_no_coordinate_appears_anywhere_in_the_map(reasoning_map):
    import re

    serialized = json.dumps(reasoning_map)
    assert not re.search(r"[-+]?\d{1,3}\.\d{3,}\s*,\s*[-+]?\d{1,3}\.\d{3,}", serialized)
    assert reasoning_map["geographic_context"]["coordinates_present"] is False
    assert reasoning_map["locality_policy"]["disclosure"] == "WITHHELD_PENDING_REVIEW"


def test_a_coordinate_in_the_graph_is_redacted_rather_than_served():
    repo = build_pollination_repository()
    edges = []
    for edge in repo.all_edges():
        payload = dict(edge.payload)
        if edge.edge_type == "co_occurs_with":
            payload["citation"] = "Recorded at -8.1234, -35.6789 on the ridge"
        edges.append(Edge(
            kg_edge_id=edge.kg_edge_id, edge_type=edge.edge_type,
            from_node_id=edge.from_node_id, to_node_id=edge.to_node_id,
            evidence_class=edge.evidence_class, payload=payload,
        ))
    leaky = execute(repository=InMemoryGraphRepository(
        nodes=list(repo.all_nodes()), edges=edges))
    serialized = json.dumps(leaky)
    assert "-8.1234" not in serialized
    assert "locality withheld" in serialized


def test_an_unpermitted_evidence_state_fails_closed():
    repo = build_pollination_repository()
    edges = [Edge(
        kg_edge_id=e.kg_edge_id, edge_type=e.edge_type, from_node_id=e.from_node_id,
        to_node_id=e.to_node_id, evidence_class="FACT", payload=e.payload,
    ) if e.kg_edge_id == 1 else e for e in repo.all_edges()]
    with pytest.raises(CognitiveIntegrationError, match="evidence state"):
        execute(repository=InMemoryGraphRepository(
            nodes=list(repo.all_nodes()), edges=edges))


def test_both_handoffs_are_available_and_bounded(reasoning_map):
    handoffs = reasoning_map["handoffs"]
    assert handoffs["research_station"]["carries_evidence_states"] is True
    assert handoffs["education"]["audience_adaptation_may_change_meaning"] is False


def test_the_path_activates_no_scientific_or_taxonomic_state(reasoning_map):
    governance = reasoning_map["governance"]
    assert governance["scientific_review_required"] is True
    for flag in ("automatic_publication", "automatic_candidate_knowledge",
                 "automatic_knowledge_promotion", "production_runtime_enabled"):
        assert governance[flag] is False


# ---------------------------------------------------------------------------
# Over HTTP, which is how Calyx will reach it
# ---------------------------------------------------------------------------


def test_calyx_can_fetch_the_reasoning_map(client):
    response = client.get("/api/cognitive-integration/reasoning-map")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["taxonomic_identity"]["accepted_name"] == "Ophrys apifera"
    assert body["execution"]["provider_calls"] == 0
    assert body["contradictions"]


def test_an_unsupported_question_is_refused_with_what_it_would_take(client):
    response = client.get(
        "/api/cognitive-integration/reasoning-map",
        params={"question": "Why are orchid seeds so small?"},
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["required_capability"] == "free-text-intent-parsing"
    assert detail["supported_questions"]


def test_the_capability_route_states_no_provider_is_needed_to_reason(client):
    body = client.get("/api/cognitive-integration/capabilities").json()
    assert body["provider_required_for_reasoning"] is False
    assert body["optional_provider"] == [OPTIONAL_CAPABILITY]


def test_the_backend_map_satisfies_the_brain_scientific_contract(reasoning_map):
    """The two repositories must agree about the science, not merely coexist.

    The Brain's validator is the authority on what a reasoning map must
    demonstrate. Running it against the backend's output is what makes the
    contract real rather than a shared intention.
    """
    import importlib.util
    import pathlib

    brain = pathlib.Path("/home/user/orchid-continuum-brain")
    script = brain / "scripts" / "oc_brain_validate_cognitive_integration.py"
    if not script.exists():
        pytest.skip("Brain checkout not present in this environment")

    spec = importlib.util.spec_from_file_location("brain_validator", script)
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)

    assert validator.check_pollination_fixture(reasoning_map) == []

    schema = json.loads((brain / validator.REASONING_MAP_SCHEMA).read_text())
    structural = validator.check_fixture_against_schema(reasoning_map, schema)
    undeclared = [f for f in structural if "undeclared key" in f]

    # Execution metadata is additive. A Brain checkout that already declares it
    # accepts the map outright; one that predates the declaration reports only
    # that single key. Anything else is a real divergence in the contract.
    assert undeclared in ([], ["fixture carries undeclared key 'execution'"]), structural
    assert [f for f in structural if "undeclared key" not in f] == [], structural


# ---------------------------------------------------------------------------
# Every citation supports the claim it is attached to
# ---------------------------------------------------------------------------


def test_sexual_deception_is_not_attributed_to_darwin(reasoning_map):
    """Darwin had no concept of sexual deception.

    Pseudocopulation in *Ophrys* was proposed by Pouyanne and Correvon in
    1916-1923 and established by Kullenberg in 1961. Citing Darwin 1862 for it
    credits him with a mechanism described more than fifty years after his book,
    and inverts what he actually wrote about this species — he recorded it as
    habitually self-fertilised and said he had never seen an insect visit it.
    """
    for relationship in reasoning_map["relationships"]:
        if relationship["predicate"] == "reported_pollinated_by":
            citation = relationship["provenance"][0]["citation"]
            assert "Darwin" not in citation
            assert "Kullenberg" in citation


def test_darwin_is_cited_for_the_claim_he_actually_made(reasoning_map):
    for relationship in reasoning_map["relationships"]:
        if relationship["predicate"] == "reported_reproductive_strategy":
            assert "Darwin" in relationship["provenance"][0]["citation"]


def test_a_nineteenth_century_monograph_is_not_recorded_as_a_journal_article(reasoning_map):
    for relationship in reasoning_map["relationships"]:
        citation = relationship["provenance"][0]["citation"]
        if "Darwin" in citation:
            assert relationship["provenance"][0]["source_type"] == "scholarly_monograph"


def test_the_scopes_do_not_overstate_a_clean_regional_split(reasoning_map):
    """Autogamy is predominant throughout the range, not a north-western mode.

    Framing the disagreement as "Mediterranean versus north-west" would be tidier
    than the record supports: insect pollination is a sporadic local exception.
    """
    scopes = {
        r["predicate"]: r.get("geographic_scope")
        for r in reasoning_map["relationships"]
        if r["predicate"] in ("reported_pollinated_by", "reported_reproductive_strategy")
    }
    assert "throughout the range" in scopes["reported_reproductive_strategy"]
    assert "sporadic" in scopes["reported_pollinated_by"]


def test_mechanism_prose_describes_the_edge_rather_than_this_fixture():
    """The wording asserted "reproduces without any insect" for any strategy edge."""
    repo = build_pollination_repository()
    nodes = []
    for node in repo.all_nodes():
        if node.canonical_key == "process:autogamy":
            node = Node(
                kg_node_id=node.kg_node_id, node_type=node.node_type,
                canonical_key=node.canonical_key,
                display_label="Insect-mediated outcrossing", payload=node.payload,
            )
        nodes.append(node)
    relabelled = execute(repository=InMemoryGraphRepository(
        nodes=nodes, edges=list(repo.all_edges())))
    competing = [m for m in relabelled["mechanisms"] if m["kind"] == "competing_mechanism"]
    assert competing
    for mechanism in competing:
        assert "without any insect" not in mechanism["statement"]
        assert "Insect-mediated outcrossing" in mechanism["statement"]


#: Shapes that carried a position past *both* nets in the second checker round.
#: Four of the five never write a digits-and-dot pair at all, which is what the
#: first widening had assumed a coordinate would look like.
_SECOND_ROUND_LEAKS = [
    ("51.7520 degrees north, 1.2577 degrees west", ["51.7520", "1.2577"]),
    ("UTM 30U 620000 5735000", ["620000", "5735000"]),
    ("51,7520 1,2577", ["51,7520", "1,2577"]),
    ("9C3XGV24+RQ", ["9C3XGV24+RQ"]),
    ("51 deg 45 min N, 1 deg 15 min W", ["51 deg 45", "1 deg 15"]),
]


@pytest.mark.parametrize("leak,fragments", _SECOND_ROUND_LEAKS)
def test_a_position_written_without_a_decimal_pair_is_still_withheld(leak, fragments):
    """The first is the same ~10 m Oxford position as the original reproduction.

    It reached a client while the response asserted ``redaction_applied: True``,
    ``WITHHELD_PENDING_REVIEW`` and ``coordinates_present: False``. Misreporting
    the safety state is worse than leaking quietly: a consumer has been told the
    field is safe.
    """
    repo = build_pollination_repository()
    edges = []
    for edge in repo.all_edges():
        payload = dict(edge.payload)
        if edge.edge_type == "co_occurs_with":
            payload["citation"] = f"Field survey. Population at {leak}."
        edges.append(Edge(
            kg_edge_id=edge.kg_edge_id, edge_type=edge.edge_type,
            from_node_id=edge.from_node_id, to_node_id=edge.to_node_id,
            evidence_class=edge.evidence_class, payload=payload,
        ))
    served = json.dumps(execute(repository=InMemoryGraphRepository(
        nodes=list(repo.all_nodes()), edges=edges)))
    for fragment in fragments:
        assert fragment not in served, f"{fragment!r} reached the client"


def test_the_fail_closed_net_is_strictly_broader_than_the_redactor():
    """Not merely a different pattern — a superset, by construction.

    If the two share one pattern the assertion can only confirm what the
    redactor already did. Asserting the property directly means a future
    widening of the redactor cannot quietly leave the assertion behind.
    """
    from app.cognitive_integration.executor import _COORDINATE, _COORDINATE_SUSPICION

    probes = [leak for leak, _ in _SECOND_ROUND_LEAKS] + [
        "Population located at 51.7520 -1.2577 near the reserve",
        "Population at 51.75, -1.25",
        "lat 51.7520 lon -1.2577",
        "Recorded at 43° 17’ N",
        "51.7520, -1.2577",
        "30U WV 20000 35000",
    ]
    for probe in probes:
        if _COORDINATE.search(probe):
            assert _COORDINATE_SUSPICION.search(probe), (
                f"the redactor catches {probe!r} but the fail-closed net does not"
            )

    # And it is genuinely wider: this one the redactor misses and the net holds.
    assert not _COORDINATE.search("N51.7520 W1.2577")
    assert _COORDINATE_SUSPICION.search("N51.7520 W1.2577")


@pytest.mark.parametrize(
    "citation",
    [
        (
            "Kullenberg, B. (1961). Studies in Ophrys pollination. "
            "Zoologiska Bidrag fran Uppsala 34: 1-340."
        ),
        "Darwin, C. (1862). On the Various Contrivances. John Murray, London.",
        "Aggregated occurrence records, country resolution only.",
        "1,234 records were aggregated for this taxon.",
    ],
)
def test_the_widened_net_does_not_eat_ordinary_citations(citation):
    """Page ranges, years and thousands separators are not coordinates.

    A redactor that mangles its own provenance would make the map unreadable to
    defend it, which is its own kind of failure.
    """
    from app.cognitive_integration.executor import _COORDINATE

    assert not _COORDINATE.search(citation)


def test_no_prose_asserts_a_difference_the_graph_does_not_carry():
    """The checker's mutation, applied to every remaining recited sentence.

    Relabelling the reproductive process to something insect-mediated used to
    leave three sentences asserting the opposite: the contradiction description
    said one report "needs no insect", the null explanation invoked a
    "non-insect strategy", and the geographic note announced a regional split
    that nothing established. Detection was derived; the descriptions were not.
    """
    import dataclasses

    repo = build_pollination_repository()
    nodes = [
        dataclasses.replace(node, display_label="Beetle-mediated outcrossing")
        if node.kg_node_id == 4
        else node
        for node in repo.all_nodes()
    ]
    served = json.dumps(
        execute(repository=InMemoryGraphRepository(nodes=nodes, edges=list(repo.all_edges())))
    )
    for false_claim in (
        "needs no insect",
        "without any insect",
        "non-insect strategy",
        "reproduces without",
    ):
        assert false_claim not in served, f"recited prose survived: {false_claim!r}"

    # And it describes what is actually there.
    assert "Beetle-mediated outcrossing" in served


def test_the_regional_split_note_requires_an_established_split():
    """D1b reworded the scopes to stop overstating a clean regional division.

    The note that announces one was still firing on "more than one distinct
    scope string", so the reworded scopes — a frequency statement and a
    frequency-plus-place statement over overlapping ground — put the
    overstatement straight back into the served map.
    """
    notes = " ".join(execute()["geographic_context"]["environmental_notes"])
    assert "differs between parts of the range" not in notes
    assert "does not divide the range" in notes


def test_a_genus_level_source_cited_for_a_species_claim_says_so():
    """Kullenberg 1961 established pseudocopulation across *Ophrys*.

    That makes it the right citation for the mechanism and a stretched one for
    *O. apifera* being insect-pollinated, since this species is the autogamous
    exception within the genus. A checker was right that the fix for the Darwin
    misattribution traded a categorical error for an over-reach.

    The reasoning-map contract fixes the provenance keys, so the qualification
    cannot ride on the citation. It is derived into the gap list instead —
    which is where a reader looking for what the evidence does not cover will
    actually look. Inventing a species-level citation nobody retrieved would be
    the same failure as citing Darwin, one step subtler.
    """
    gaps = execute()["evidence_gaps"]
    qualified = [g for g in gaps if "at genus level" in g]
    assert qualified, "the genus-level limitation must be stated, not implied"
    assert "reported_pollinated_by" in qualified[0]
    assert "nothing retrieved reports it for this species specifically" in qualified[0]


def test_the_genus_level_qualifier_is_derived_and_not_a_fixed_sentence():
    """Remove the qualifier from the edge and the gap must disappear."""
    repo = build_pollination_repository()
    edges = []
    for edge in repo.all_edges():
        payload = {k: v for k, v in (edge.payload or {}).items() if k != "support_scope"}
        edges.append(Edge(
            kg_edge_id=edge.kg_edge_id, edge_type=edge.edge_type,
            from_node_id=edge.from_node_id, to_node_id=edge.to_node_id,
            evidence_class=edge.evidence_class, payload=payload,
        ))
    gaps = execute(repository=InMemoryGraphRepository(
        nodes=list(repo.all_nodes()), edges=edges))["evidence_gaps"]
    assert not [g for g in gaps if "at genus level" in g]


def test_routing_fields_never_reach_the_client():
    """``scope_region`` and ``support_scope`` decide things; they do not claim them.

    The reasoning-map contract sets ``additionalProperties: false`` on a
    relationship, so leaking either would break the Brain contract as well as
    publishing an internal decision as though it were evidence.
    """
    served = execute()
    for relationship in served["relationships"]:
        assert "scope_region" not in relationship
        assert "support_scope" not in relationship


#: Shapes a third checker carried past both nets, each served verbatim while
#: the response asserted `coordinates_present: False`.
_THIRD_ROUND_LEAKS = [
    ("Ordnance Survey grid", "SP 5106 0634"),
    ("OS grid, unspaced", "SP51060634"),
    ("OS grid, ten figure", "TL 12345 67890"),
    ("geohash", "gcpvj0duq"),
    ("full-width digits", "５１．７５２０, －１．２５７７"),
    ("Arabic-Indic digits", "٥١٫٧٥٢٠ ١٫٢٥٧٧"),
    ("degrees-minutes-seconds, no units", "51 45 07 N 001 15 27 W"),
    ("scientific notation", "5.17520e1, -1.2577e0"),
    ("digits spaced apart", "5 1 . 7 5 2 0 , - 1 . 2 5 7 7"),
    ("bare what3words", "filled.count.soap"),
]


@pytest.mark.parametrize("label,leak", _THIRD_ROUND_LEAKS)
def test_the_national_grid_and_its_relatives_are_withheld(label, leak):
    """Ordnance Survey is the one that matters most here.

    UTM and MGRS — the international and military grids — were covered while
    the national grid of the country this fixture is about was not. A British
    recorder writes an OS reference; the worked position throughout this module
    is Oxford. It was the likeliest real input and the one shape missing.
    """
    repo = build_pollination_repository()
    edges = []
    for edge in repo.all_edges():
        payload = dict(edge.payload)
        if edge.edge_type == "co_occurs_with":
            payload["citation"] = f"Recorded at {leak}."
        edges.append(Edge(
            kg_edge_id=edge.kg_edge_id, edge_type=edge.edge_type,
            from_node_id=edge.from_node_id, to_node_id=edge.to_node_id,
            evidence_class=edge.evidence_class, payload=payload,
        ))
    # `ensure_ascii=False`, or the comparison is vacuous: json.dumps escapes
    # non-ASCII by default, so a full-width or Arabic-Indic position would
    # never appear in the haystack and the assertion could not fail. Caught by
    # mutation testing — the digit-folding mutation left this green.
    served = json.dumps(
        execute(repository=InMemoryGraphRepository(
            nodes=list(repo.all_nodes()), edges=edges)),
        ensure_ascii=False,
    )
    assert leak not in served, f"{label} reached the client"


def test_a_position_carried_as_numbers_is_examined_like_any_other():
    """The redactor returned every non-string unexamined.

    Two edges carrying `51.7520` and `-1.2577` as floats were served intact,
    and the fail-closed check missed them too because the halves sat further
    apart than its window. That is the shape a real occurrence record is most
    likely to arrive in, and checking only strings is a bug class rather than a
    missing pattern.
    """
    repo = build_pollination_repository()
    edges = []
    for edge in repo.all_edges():
        payload = dict(edge.payload)
        if edge.kg_edge_id == 4:
            payload["identifier"] = 51.7520
        if edge.kg_edge_id == 5:
            payload["identifier"] = -1.2577
        edges.append(Edge(
            kg_edge_id=edge.kg_edge_id, edge_type=edge.edge_type,
            from_node_id=edge.from_node_id, to_node_id=edge.to_node_id,
            evidence_class=edge.evidence_class, payload=payload,
        ))
    result = execute(repository=InMemoryGraphRepository(
        nodes=list(repo.all_nodes()), edges=edges))
    served = json.dumps(result)
    assert "51.752" not in served
    assert "-1.2577" not in served
    assert result["geographic_context"]["coordinates_present"] is True


def test_the_map_reports_what_redaction_did_instead_of_asserting_it():
    """`coordinates_present` was a literal `False`.

    So every shape the pattern missed was served with a positive assertion that
    the map was clean — worse than the miss, because a consumer cannot defend
    itself against a field that lies. It is derived now, which also lets the
    layers compose: a rendering surface that finds a position in a map
    declaring `False` has caught a real upstream miss.
    """
    clean = execute()
    assert clean["geographic_context"]["coordinates_present"] is False

    repo = build_pollination_repository()
    edges = []
    for edge in repo.all_edges():
        payload = dict(edge.payload)
        if edge.edge_type == "co_occurs_with":
            payload["citation"] = "Recorded at 51.7520, -1.2577."
        edges.append(Edge(
            kg_edge_id=edge.kg_edge_id, edge_type=edge.edge_type,
            from_node_id=edge.from_node_id, to_node_id=edge.to_node_id,
            evidence_class=edge.evidence_class, payload=payload,
        ))
    poisoned = execute(repository=InMemoryGraphRepository(
        nodes=list(repo.all_nodes()), edges=edges))
    assert poisoned["geographic_context"]["coordinates_present"] is True
    assert "51.7520" not in json.dumps(poisoned)


def test_redaction_applied_still_records_that_the_policy_ran():
    """Not derived from the substitution count, and that is deliberate.

    The Brain's scientific contract reads this as "the redaction policy is in
    force for a protected taxon", not "a substitution occurred". For a
    protected taxon whose sources carry no coordinates the policy did run and
    found nothing, so deriving this one would break that contract and would
    say something false.
    """
    assert execute()["locality_policy"]["redaction_applied"] is True


def test_ordinary_quantitative_prose_does_not_take_the_whole_map_down():
    """The fail-closed net raised on "12.5 percent over 3.5 seasons".

    `quantified_seed_set` is one of this module's own EXPECTED_BUT_ABSENT
    predicates, so the evidence it says it most wants was the shape that broke
    it. Every real coordinate form carries two decimal places or more.
    """
    repo = build_pollination_repository()
    edges = []
    for edge in repo.all_edges():
        payload = dict(edge.payload)
        if edge.edge_type == "co_occurs_with":
            payload["citation"] = "Seed set fell by 12.5 percent over 3.5 seasons."
        edges.append(Edge(
            kg_edge_id=edge.kg_edge_id, edge_type=edge.edge_type,
            from_node_id=edge.from_node_id, to_node_id=edge.to_node_id,
            evidence_class=edge.evidence_class, payload=payload,
        ))
    served = execute(repository=InMemoryGraphRepository(
        nodes=list(repo.all_nodes()), edges=edges))
    assert "12.5 percent over 3.5 seasons" in json.dumps(served)


def test_the_next_evidence_no_longer_promises_the_rule_this_module_removed():
    """It said such a source "would resolve the contradiction by scope".

    Under the rule now implemented, two incompatible claims about one
    population is the definition of a live conflict. The sentence was the
    inverted rule written in prose: the map recommended evidence and stated the
    opposite of what the code does with it.
    """
    served = execute()
    text = " ".join(served["recommended_next_evidence"])
    assert "resolve the contradiction by scope" not in text
    assert "assessed within a single place" in text


def test_known_unknowns_count_what_the_graph_holds():
    """They asserted "the two reproductive strategies" as a fixed sentence."""
    import dataclasses

    repo = build_pollination_repository()
    nodes = [
        dataclasses.replace(node, display_label="Beetle-mediated outcrossing")
        if node.kg_node_id == 4
        else node
        for node in repo.all_nodes()
    ]
    served = execute(repository=InMemoryGraphRepository(
        nodes=nodes, edges=list(repo.all_edges())))
    text = " ".join(served["known_unknowns"])
    assert "Beetle-mediated outcrossing" in text
    assert "the insect-mediated mechanism is currently active" not in text


def test_a_scope_resolution_says_what_declared_the_places_separate():
    """The one inference here that deletes a disagreement was unauditable.

    The served contradiction reported `resolved_by_scope` with no indication
    that a `disjoint_from` edge existed or what stood behind it.
    """
    repo = build_pollination_repository()
    resolved = execute(
        repository=_with_scope_regions(
            repo, "region:mediterranean", "region:north-western-europe"
        )
    )
    contradiction = resolved["contradictions"][0]
    assert contradiction["resolution"] == "resolved_by_scope"
    assert contradiction["resolved_by"], "a deleted disagreement must cite what deleted it"
    assert "occurrence records" in contradiction["resolved_by"]

    # And nothing is claimed when nothing resolved.
    assert execute()["contradictions"][0]["resolved_by"] is None
