import pytest

from app.routers import matrix_relationship as router
from app.routers.matrix_relationship import CanonicalSourceMatrixRequest


@pytest.mark.parametrize("genus", [None, "Phalaenopsis", "Paphiopedilum"])
def test_canonical_matrix_response_attests_exact_requested_genus(monkeypatch, genus):
    seen = {}

    def fake_load(database_url, *, dimension, subject_ids, genus, limit):
        seen.update(
            database_url=database_url,
            dimension=dimension,
            subject_ids=subject_ids,
            genus=genus,
            limit=limit,
        )
        return []

    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    monkeypatch.setattr(router, "load_governed_assertions", fake_load)

    payload = CanonicalSourceMatrixRequest(
        dimension="trait",
        genus=genus,
        subject_ids=["101"],
        limit=25,
    )
    response = router.build_from_canonical_source(payload, None)

    assert seen["genus"] == genus
    assert response["source_mode"] == "canonical_governed_source"
    assert response["genus_scope"] == genus
    assert response["read_only"] is True
    assert response["canonical_graph_mutation"] is False


def test_invalid_genus_cannot_reach_canonical_source_read(monkeypatch):
    called = False

    def fake_load(*_args, **_kwargs):
        nonlocal called
        called = True
        return []

    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    monkeypatch.setattr(router, "load_governed_assertions", fake_load)

    with pytest.raises(Exception):
        CanonicalSourceMatrixRequest(dimension="trait", genus="Phalaenopsis amabilis")

    assert called is False
