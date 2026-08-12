from app.calyx_conversation.workspace_outputs import matrix_identification_table
from app.routers import matrix_identification


def test_matrix_workspace_output_is_bounded_derived_ranking():
    report = {"observation_count": 3, "compared_character_count": 3, "candidates": [{"taxon_id": f"taxon-{index}", "scientific_name": f"Taxon {index}", "score": 1 - (index / 100), "coverage": 0.8, "compared_weight": 3} for index in range(25)]}
    output = matrix_identification_table(report)
    assert output is not None
    assert output["kind"] == "table"
    assert output["provenance"]["source_module"] == "matrix-identification"
    assert output["provenance"]["generated"] is True
    assert output["provenance"]["evidence_status"] == "derived"
    assert len(output["payload"]["rows"]) == 20
    assert "does not assert a verified identification" in output["subtitle"]


def test_matrix_workspace_output_preserves_full_accepted_taxon_ids():
    shared_prefix = "taxon:" + ("x" * 185)
    first_id = shared_prefix + "A"
    second_id = shared_prefix + "B"
    report = {"observation_count": 1, "compared_character_count": 1, "candidates": [{"taxon_id": first_id, "scientific_name": "Taxon alpha", "score": 1.0, "coverage": 1.0, "compared_weight": 1}, {"taxon_id": second_id, "scientific_name": "Taxon beta", "score": 0.5, "coverage": 1.0, "compared_weight": 1}]}
    output = matrix_identification_table(report)
    assert output is not None
    rows = output["payload"]["rows"]
    assert rows[0]["taxon_id"] == first_id
    assert rows[1]["taxon_id"] == second_id
    assert rows[0]["taxon_id"] != rows[1]["taxon_id"]


def test_empty_matrix_report_creates_no_workspace_output():
    assert matrix_identification_table({"candidates": []}) is None
    assert matrix_identification_table({}) is None


def test_evaluate_preserves_ranking_and_returns_one_derived_workspace_panel():
    payload = matrix_identification.IdentificationRequest(observations=[matrix_identification.ObservationInput(character="flower_color", value="white", certainty="certain", weight=1)], candidates=[matrix_identification.CandidateInput(taxon_id="t1", scientific_name="Taxon alpha", states={"flower_color": "white"}, provenance={"source": "test governed matrix"}), matrix_identification.CandidateInput(taxon_id="t2", scientific_name="Taxon beta", states={"flower_color": "red"}, provenance={"source": "test governed matrix"})], limit=20)
    result = matrix_identification.evaluate(payload, {})
    assert result["candidates"][0]["taxon_id"] == "t1"
    assert result["candidates"][0]["score"] == 1.0
    assert len(result["workspace_outputs"]) == 1
    panel = result["workspace_outputs"][0]
    assert panel["provenance"]["evidence_status"] == "derived"
    assert panel["payload"]["rows"][0]["taxon_id"] == "t1"
    assert "verified identification" in panel["subtitle"]


def test_contract_keeps_mutation_and_identification_boundaries_explicit():
    contract = matrix_identification.contract({})
    assert contract["workspace_outputs"]["evidence_status"] == "derived"
    assert contract["canonical_taxonomy_mutation"] is False
    assert contract["collection_record_mutation"] is False
    assert any("do not assert an identification" in rule for rule in contract["rules"])
