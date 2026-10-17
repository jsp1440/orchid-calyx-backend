"""Proofs for the scope test applied to conflicting reports (backend #1741).

The bee-orchid question finds two reports that disagree. The operation added
for it may find them compatible only when they are established to describe
separate places; otherwise it leaves them contested and says why. It never
weights, prefers, or drops either report.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.cognitive_integration.contested_scope import (
    COMPATIBLE_BY_SCOPE,
    CONTESTED,
    LEAVE_CONTESTED,
    NO_CITATION,
    OPERATION,
    RESOLVED_BY_SCOPE,
    ScopeAdjudication,
    ScopeReason,
    adjudicate,
    has_visible_content,
    is_citation,
)
from app.cognitive_integration.executor import contradiction_adjudication, execute
from app.cognitive_integration.fixture import build_pollination_repository
from app.cognitive_integration.improvement_discovery import Deficiency, discover
from app.main import app
from runtime.knowledge_graph import Edge
from runtime.knowledge_graph.repository import InMemoryGraphRepository

POLLINATED = "reported_pollinated_by Eucera (solitary bees)"
SELFING = "reported_reproductive_strategy Habitual self-pollination"
DISJOINT = {frozenset({"region:a", "region:b"})}


def _report(predicate: str, obj: str, region: str | None = None) -> dict:
    return {"predicate": predicate, "object": obj, "scope_region": region}


def _pair(first_region: str | None, second_region: str | None):
    return (
        _report("reported_pollinated_by", "Eucera (solitary bees)", first_region),
        _report(
            "reported_reproductive_strategy", "Habitual self-pollination", second_region
        ),
    )


def _with_scope_regions(
    first_region: str, second_region: str
) -> InMemoryGraphRepository:
    repo = build_pollination_repository()
    regions = iter((first_region, second_region))
    edges = []
    for edge in repo.all_edges():
        if edge.edge_type in (
            "reported_pollinated_by",
            "reported_reproductive_strategy",
        ):
            edge = Edge(
                kg_edge_id=edge.kg_edge_id,
                edge_type=edge.edge_type,
                from_node_id=edge.from_node_id,
                to_node_id=edge.to_node_id,
                evidence_class=edge.evidence_class,
                payload={**edge.payload, "scope_region": next(regions)},
            )
        edges.append(edge)
    return InMemoryGraphRepository(nodes=list(repo.all_nodes()), edges=edges)


# ---------------------------------------------------------------------------
# The bee-orchid case
# ---------------------------------------------------------------------------


def test_the_bee_orchid_conflict_is_evaluated_and_left_contested():
    records = contradiction_adjudication()
    assert len(records) == 1
    record = records[0]
    assert record["operation"] == OPERATION
    assert record["between"] == [POLLINATED, SELFING]
    assert record["reason"] == ScopeReason.SCOPE_ABSENT_BOTH.value
    assert record["decision"] == LEAVE_CONTESTED
    assert record["resolution"] == CONTESTED
    assert record["resolved_by"] is None
    assert "structured region" in record["would_change_if"]


def test_the_operation_agrees_with_the_served_map():
    """The map and the audit trail come from the same pairs and the same rule."""
    reasoning_map = execute()
    records = contradiction_adjudication()
    assert [c["between"] for c in reasoning_map["contradictions"]] == [
        r["between"] for r in records
    ]
    assert [c["resolution"] for c in reasoning_map["contradictions"]] == [
        r["resolution"] for r in records
    ]


def test_both_reports_survive_with_their_provenance():
    reasoning_map = execute()
    served = {
        f"{r['predicate']} {r['object']}": r for r in reasoning_map["relationships"]
    }
    for report in (POLLINATED, SELFING):
        assert report in served
        assert served[report]["provenance"][0]["citation"]
    record = contradiction_adjudication()[0]
    assert record["reports_retained"] == 2
    assert record["preferred_report"] is None
    assert record["weighting_applied"] is False
    assert record["requires_human_review"] is True
    assert record["may_activate_scientific_conclusion"] is False


def test_the_served_map_still_carries_no_routing_input():
    """The audit trail is served beside the map, not in it: the Brain closes the map."""
    reasoning_map = execute()
    assert "contradiction_adjudication" not in reasoning_map["execution"]
    for contradiction in reasoning_map["contradictions"]:
        assert set(contradiction) == {
            "between",
            "description",
            "resolution",
            "scopes",
            "resolved_by",
        }
    # Structured region keys are routing input: the record says only whether
    # each report declared one, never which.
    scoped = contradiction_adjudication(
        _with_scope_regions("region:mediterranean", "region:north-western-europe")
    )
    assert "region:" not in json.dumps(scoped)
    assert scoped[0]["scope_region_declared"] == [True, True]


# ---------------------------------------------------------------------------
# The scope test itself
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("first", "second", "reason"),
    [
        (None, None, ScopeReason.SCOPE_ABSENT_BOTH),
        ("", None, ScopeReason.SCOPE_ABSENT_BOTH),
        ("region:a", None, ScopeReason.SCOPE_ABSENT_ONE),
        (None, "region:b", ScopeReason.SCOPE_ABSENT_ONE),
        ("region:a", "region:a", ScopeReason.SAME_REGION),
        ("region:a", "region:elsewhere", ScopeReason.DISJOINTNESS_NOT_ESTABLISHED),
    ],
)
def test_everything_short_of_declared_disjointness_stays_contested(
    first, second, reason
):
    verdict = adjudicate(*_pair(first, second), DISJOINT)
    assert verdict.reason is reason
    assert verdict.resolution == CONTESTED
    assert verdict.decision == LEAVE_CONTESTED
    assert verdict.resolved_by is None


def test_absent_scopes_stay_contested_even_when_the_graph_declares_disjoint_regions():
    """The graph declaring two regions separate says nothing about reports with no region."""
    verdict = adjudicate(
        *_pair(None, None), DISJOINT, {frozenset({"region:a", "region:b"}): "x"}
    )
    assert verdict.resolution == CONTESTED
    assert verdict.disjointness_declared is False


def test_declared_disjoint_regions_make_the_reports_compatible_and_cite_why():
    verdict = adjudicate(
        *_pair("region:a", "region:b"),
        DISJOINT,
        {frozenset({"region:a", "region:b"}): "Cited"},
    )
    assert verdict.reason is ScopeReason.DISJOINT_DECLARED
    assert verdict.resolution == RESOLVED_BY_SCOPE
    assert verdict.decision == COMPATIBLE_BY_SCOPE
    assert verdict.resolved_by == "Cited"
    # Compatible is not a winner: both are still retained, neither preferred.
    assert verdict.reports_retained == 2
    assert verdict.preferred_report is None


@pytest.mark.parametrize(
    "provenance",
    [
        None,
        {},
        {frozenset({"region:a", "region:b"}): ""},
        {frozenset({"region:a", "region:b"}): "   \t\n"},
        {frozenset({"region:a", "region:b"}): NO_CITATION},
        {frozenset({"region:a", "region:b"}): "  No Citation Recorded  "},
        {frozenset({"region:a", "region:b"}): None},
        {frozenset({"region:a", "region:b"}): "\u200b"},
        {frozenset({"region:a", "region:b"}): "\ufeff"},
        {frozenset({"region:a", "region:b"}): "no citation recorded\u200b"},
        {frozenset({"region:a", "region:b"}): " \u2060\u00a0\u200d\u3000 "},
        {frozenset({"region:a", "region:b"}): "no\u200b citation\u00ad recorded"},
        {frozenset({"region:a", "region:b"}): "\uff4eo citation recorded"},
        {frozenset({"region:a", "region:b"}): 42},
        {frozenset({"region:a", "region:b"}): {"citation": "x"}},
    ],
    ids=[
        "none",
        "missing",
        "empty",
        "whitespace",
        "placeholder",
        "placeholder-case",
        "null",
        "zero-width-space",
        "byte-order-mark",
        "placeholder-zero-width",
        "format-and-unicode-space",
        "placeholder-interleaved-format",
        "placeholder-fullwidth",
        "int",
        "dict",
    ],
)
def test_declared_disjointness_without_a_real_citation_stays_contested(provenance):
    """Checker FAIL on #1966: the truthy placeholder resolved an uncited edge."""
    verdict = adjudicate(*_pair("region:a", "region:b"), DISJOINT, provenance)
    assert verdict.reason is ScopeReason.DISJOINTNESS_UNCITED
    assert verdict.resolution == CONTESTED
    assert verdict.decision == LEAVE_CONTESTED
    assert verdict.resolved_by is None
    assert verdict.disjointness_declared is True
    assert "citable source" in verdict.to_record()["would_change_if"]


@pytest.mark.parametrize("blank", ["", " ", "\t", "  \n "])
def test_a_whitespace_region_is_absent(blank):
    both = adjudicate(*_pair(blank, blank), DISJOINT)
    assert both.reason is ScopeReason.SCOPE_ABSENT_BOTH
    assert both.scope_region_declared == (False, False)
    one = adjudicate(*_pair("region:a", blank), DISJOINT)
    assert one.reason is ScopeReason.SCOPE_ABSENT_ONE
    assert one.resolution == CONTESTED


#: Blank-looking inputs from the third re-check, plus placeholder spellings.
_BLANK_LOOKING = {
    "combining-acute": "\u0301",
    "enclosing-circle": "\u20dd",
    "cyrillic-hundred-thousands": "\u0488",
    "nul": "\x00",
    "bel-esc": "\x07\x1b",
    "private-use-bmp": "\ue000",
    "private-use-plane-15": "\U000f0000",
    "hangul-filler": "\u3164",
    "hangul-choseong-filler": "\u115f",
    "hangul-jungseong-filler": "\u1160",
    "halfwidth-hangul-filler": "\uffa0",
    "braille-blank": "\u2800",
    "mixed-blank": " \u0301\x00\ue000\u3164\u2800\u200b ",
    "placeholder-double-space": "no  citation recorded",
    "placeholder-zero-width-joined": "no\u200bcitation recorded",
    "placeholder-punctuated": "No-Citation_Recorded!",
}


@pytest.mark.parametrize("value", _BLANK_LOOKING.values(), ids=_BLANK_LOOKING.keys())
def test_a_blank_looking_citation_or_placeholder_never_resolves(value):
    """Re-check FAIL on #1966: anything without a visible letter or number."""
    assert not is_citation(value)
    verdict = adjudicate(
        *_pair("region:a", "region:b"),
        DISJOINT,
        {frozenset({"region:a", "region:b"}): value},
    )
    assert verdict.reason is ScopeReason.DISJOINTNESS_UNCITED
    assert verdict.resolution == CONTESTED
    assert verdict.resolved_by is None
    with pytest.raises(ValueError, match="SCOPE_TEST_AUDIT"):
        _adjudication(
            reason=ScopeReason.DISJOINT_DECLARED,
            disjointness_declared=True,
            resolved_by=value,
        )
    if not has_visible_content(value):
        # A blank-looking region is absent; the placeholder spellings are
        # ordinary visible text and are only special as citations.
        assert adjudicate(*_pair(value, value), DISJOINT).reason is (
            ScopeReason.SCOPE_ABSENT_BOTH
        )


def test_every_non_placeholder_blank_looking_input_has_no_visible_content():
    blank = {k: v for k, v in _BLANK_LOOKING.items() if not k.startswith("placeholder")}
    assert not any(has_visible_content(v) for v in blank.values())


def test_visible_text_is_still_a_citation():
    assert is_citation("Kullenberg 1961")
    assert is_citation("1961")
    # Homoglyphs are visible text by design and are not chased.
    assert is_citation("\u043eno citation recorded")


def test_a_citation_with_format_characters_is_served_as_visible_text():
    verdict = adjudicate(
        *_pair("region:a", "region:b"),
        DISJOINT,
        {frozenset({"region:a", "region:b"}): "\ufeff Kullenberg 1961\u200b "},
    )
    assert verdict.resolution == RESOLVED_BY_SCOPE
    assert verdict.resolved_by == "Kullenberg 1961"


@pytest.mark.parametrize("blank", ["\u200b", "\ufeff", " \u2060 "])
def test_a_format_character_region_is_absent(blank):
    assert (
        adjudicate(*_pair(blank, blank), DISJOINT).reason
        is ScopeReason.SCOPE_ABSENT_BOTH
    )


def test_a_padded_region_is_compared_by_its_key():
    verdict = adjudicate(
        *_pair(" region:a ", "region:b\n"),
        DISJOINT,
        {frozenset({"region:a", "region:b"}): " Cited "},
    )
    assert verdict.resolution == RESOLVED_BY_SCOPE
    assert verdict.resolved_by == "Cited"


def _with_disjoint_citation(citation) -> InMemoryGraphRepository:
    repo = _with_scope_regions("region:mediterranean", "region:north-western-europe")
    edges = []
    for edge in repo.all_edges():
        if edge.edge_type == "disjoint_from":
            payload = {**edge.payload, "citation": citation}
            edge = Edge(
                kg_edge_id=edge.kg_edge_id,
                edge_type=edge.edge_type,
                from_node_id=edge.from_node_id,
                to_node_id=edge.to_node_id,
                evidence_class=edge.evidence_class,
                payload=payload,
            )
        edges.append(edge)
    return InMemoryGraphRepository(nodes=list(repo.all_nodes()), edges=edges)


@pytest.mark.parametrize(
    "citation",
    [
        None,
        "",
        "   ",
        NO_CITATION,
        "\u200b",
        "\ufeff",
        NO_CITATION + "\u200b",
        42,
        {"a": 1},
    ],
)
def test_an_uncited_disjoint_edge_does_not_resolve_end_to_end(citation):
    repo = _with_disjoint_citation(citation)
    record = contradiction_adjudication(repo)[0]
    assert record["reason"] == ScopeReason.DISJOINTNESS_UNCITED.value
    assert record["decision"] == LEAVE_CONTESTED
    assert record["resolved_by"] is None
    contradiction = execute(repository=repo)["contradictions"][0]
    assert contradiction["resolution"] == CONTESTED
    assert contradiction["resolved_by"] is None
    candidates = discover(execute(repository=repo), contradiction_adjudication(repo))
    conflict = [c for c in candidates if "Two reports conflict" in c.statement]
    assert conflict[0].deficiency is Deficiency.MISSING_EVIDENCE
    assert "citable source" in conflict[0].bounded_next_step


def test_the_outcome_does_not_depend_on_evidence_strength_or_order():
    """No weighting: a SUPPORTED report does not beat a CONTESTED one."""
    first, second = _pair(None, None)
    strong = {**first, "evidence_state": "SUPPORTED"}
    weak = {**second, "evidence_state": "CONTESTED"}
    forward = adjudicate(strong, weak, DISJOINT)
    backward = adjudicate(weak, strong, DISJOINT)
    assert forward.resolution == backward.resolution == CONTESTED
    assert forward.reason is backward.reason


def test_end_to_end_disjoint_regions_resolve_and_undeclared_do_not():
    resolved = contradiction_adjudication(
        _with_scope_regions("region:mediterranean", "region:north-western-europe")
    )[0]
    assert resolved["decision"] == COMPATIBLE_BY_SCOPE
    assert "occurrence records" in resolved["resolved_by"]

    contested = contradiction_adjudication(
        _with_scope_regions("region:mediterranean", "region:invented-elsewhere")
    )[0]
    assert contested["decision"] == LEAVE_CONTESTED
    assert contested["reason"] == ScopeReason.DISJOINTNESS_NOT_ESTABLISHED.value


# ---------------------------------------------------------------------------
# It cannot pick a winner, hide a report, or certify itself
# ---------------------------------------------------------------------------


def _adjudication(**overrides) -> ScopeAdjudication:
    base = {
        "between": (POLLINATED, SELFING),
        "reason": ScopeReason.SCOPE_ABSENT_BOTH,
        "scope_region_declared": (False, False),
        "disjointness_declared": False,
        "resolved_by": None,
    }
    base.update(overrides)
    return ScopeAdjudication(**base)


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"weighting_applied": True}, "SCOPE_TEST_NO_WEIGHTING"),
        ({"preferred_report": POLLINATED}, "SCOPE_TEST_NO_WINNER"),
        ({"reports_retained": 1}, "SCOPE_TEST_RETAINS_BOTH"),
        ({"between": (POLLINATED,), "reports_retained": 1}, "SCOPE_TEST_RETAINS_BOTH"),
        ({"requires_human_review": False}, "SCOPE_TEST_REVIEW_INVARIANT"),
        ({"may_activate_scientific_conclusion": True}, "SCOPE_TEST_REVIEW_INVARIANT"),
        ({"disjointness_declared": True}, "SCOPE_TEST_DISJOINTNESS"),
        ({"resolved_by": "fiat"}, "SCOPE_TEST_AUDIT"),
        (
            {
                "reason": ScopeReason.DISJOINT_DECLARED,
                "disjointness_declared": True,
                "resolved_by": NO_CITATION,
            },
            "SCOPE_TEST_AUDIT",
        ),
        (
            {
                "reason": ScopeReason.DISJOINT_DECLARED,
                "disjointness_declared": True,
                "resolved_by": "   ",
            },
            "SCOPE_TEST_AUDIT",
        ),
        (
            {
                "reason": ScopeReason.DISJOINT_DECLARED,
                "disjointness_declared": True,
                "resolved_by": "no citation recorded\u200b",
            },
            "SCOPE_TEST_AUDIT",
        ),
        (
            {
                "reason": ScopeReason.DISJOINT_DECLARED,
                "disjointness_declared": True,
                "resolved_by": "\ufeff",
            },
            "SCOPE_TEST_AUDIT",
        ),
        (
            {
                "reason": ScopeReason.DISJOINTNESS_UNCITED,
                "disjointness_declared": False,
            },
            "SCOPE_TEST_DISJOINTNESS",
        ),
        (
            {"reason": ScopeReason.DISJOINT_DECLARED, "disjointness_declared": True},
            "SCOPE_TEST_AUDIT",
        ),
    ],
)
def test_an_adjudication_that_could_decide_the_science_cannot_be_built(overrides, code):
    with pytest.raises(ValueError, match=code):
        _adjudication(**overrides)


# ---------------------------------------------------------------------------
# Discovery routes the remaining gap to evidence, not to engineering
# ---------------------------------------------------------------------------


def test_an_adjudicated_conflict_is_a_scope_evidence_gap_not_a_missing_operation():
    candidates = discover(execute(), contradiction_adjudication())
    kinds = {c.deficiency for c in candidates}
    assert Deficiency.MISSING_REASONING_OPERATION not in kinds
    conflict = [c for c in candidates if "Two reports conflict" in c.statement]
    assert len(conflict) == 1
    assert conflict[0].deficiency is Deficiency.MISSING_EVIDENCE
    assert OPERATION in conflict[0].statement
    assert POLLINATED in conflict[0].statement and SELFING in conflict[0].statement
    assert "structured region" in conflict[0].bounded_next_step
    assert conflict[0].requires_human_review is True
    assert conflict[0].may_activate_scientific_conclusion is False


def test_without_an_adjudication_the_conflict_is_still_a_missing_operation():
    """Back-compatible: a map nobody adjudicated keeps the original classification."""
    kinds = {c.deficiency for c in discover(execute())}
    assert Deficiency.MISSING_REASONING_OPERATION in kinds


def test_an_adjudication_for_a_different_pair_does_not_suppress_the_candidate():
    unrelated = {**contradiction_adjudication()[0], "between": ["something", "else"]}
    kinds = {c.deficiency for c in discover(execute(), [unrelated])}
    assert Deficiency.MISSING_REASONING_OPERATION in kinds


# ---------------------------------------------------------------------------
# Over HTTP
# ---------------------------------------------------------------------------


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def test_the_adjudication_is_served(client):
    response = client.get("/api/cognitive-integration/contradiction-adjudication")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["operation"] == OPERATION
    assert body["adjudications"][0]["decision"] == LEAVE_CONTESTED
    assert body["authority"] == {
        "requires_human_review": True,
        "weighting_applied": False,
        "may_activate_scientific_conclusion": False,
    }


def test_the_served_candidates_use_the_adjudication(client):
    body = client.get("/api/cognitive-integration/improvement-candidates").json()
    assert "missing_reasoning_operation" not in body["by_deficiency"]
    statements = [c["statement"] for c in body["by_deficiency"]["missing_evidence"]]
    assert any(OPERATION in s for s in statements)


def test_an_unsupported_question_is_refused(client):
    response = client.get(
        "/api/cognitive-integration/contradiction-adjudication",
        params={"question": "x"},
    )
    assert response.status_code == 422
