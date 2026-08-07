from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.matrix_relationship import router
from runtime.matrix_relationship import (
    RelationshipAssertion,
    build_relationship_matrix,
    compare_subjects,
)


def assertion(subject: str, obj: str, state: str, confidence: float | None = None):
    return RelationshipAssertion(
        subject_id=subject,
        subject_label=subject.title(),
        dimension="pollinator",
        object_id=obj,
        object_label=obj.title(),
        state=state,
        confidence=confidence,
        provenance={"source": f"source-{subject}-{obj}-{state}"},
    )


def test_not_recorded_is_distinct_from_absent():
    matrix = build_relationship_matrix(
        [assertion("taxon-a", "bee", "absent")],
        dimension="pollinator",
        subject_ids=["taxon-a", "taxon-b"],
        object_ids=["bee"],
    )
    by_subject = {cell["subject_id"]: cell for cell in matrix["cells"]}
    assert by_subject["taxon-a"]["state"] == "absent"
    assert by_subject["taxon-b"]["state"] == "not_recorded"


def test_present_and_absent_collapse_to_conflicting_with_provenance():
    matrix = build_relationship_matrix(
        [
            assertion("taxon-a", "bee", "present", 0.9),
            assertion("taxon-a", "bee", "absent", 0.7),
        ],
        dimension="pollinator",
    )
    cell = matrix["cells"][0]
    assert cell["state"] == "conflicting"
    assert cell["assertion_count"] == 2
    assert cell["confidence"] == 0.8
    assert len(cell["provenance"]) == 2


def test_subject_comparison_preserves_states():
    matrix = build_relationship_matrix(
        [
            assertion("taxon-a", "bee", "present"),
            assertion("taxon-b", "bee", "absent"),
            assertion("taxon-a", "moth", "present"),
            assertion("taxon-b", "moth", "present"),
        ],
        dimension="pollinator",
    )
    report = compare_subjects(matrix, "taxon-a", "taxon-b")
    assert report["shared_present"] == 1
    assert report["present_absent_disagreements"] == 1


def test_api_is_owner_gated():
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    denied = client.post(
        "/api/matrix-relationship/build",
        json={"dimension": "pollinator", "assertions": []},
    )
    assert denied.status_code in {401, 403, 503}
