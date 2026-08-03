from app.species_exhibit.service import CONTRACT, _state


def test_contract_is_stable():
    assert CONTRACT == "calyx-species-exhibit-v1"


def test_unavailable_is_not_zero():
    result = _state(None, limitation="not connected")
    assert result["state"] == "unavailable"
    assert result["value"] is None
    assert result["limitation"] == "not connected"


def test_available_empty_is_not_fabricated():
    result = _state([])
    assert result["state"] == "unavailable"


def test_available_evidence_is_preserved():
    payload = {"taxon_id": "42", "scientific_name": "Cattleya labiata"}
    result = _state(payload)
    assert result["state"] == "available"
    assert result["value"] == payload
