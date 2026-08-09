from __future__ import annotations

import pytest

from runtime.orchid_show_operations import OrchidShowOperations
from runtime.volunteer_service import VolunteerService


def _service(tmp_path):
    volunteers = VolunteerService(tmp_path / "volunteers")
    volunteers.save_profile(
        "owner@example.org",
        {
            "volunteer_id": "vol-1",
            "display_name": "Show Volunteer",
            "roles": ["show table"],
            "skills": ["orchid handling"],
            "privacy_level": "private",
        },
    )
    return OrchidShowOperations(tmp_path / "shows", volunteers=volunteers)


def _seed(service: OrchidShowOperations) -> None:
    owner = "owner@example.org"
    service.create_show(
        owner,
        {
            "show_id": "fcos-2026",
            "name": "FCOS Orchid Show",
            "organization_name": "Five Cities Orchid Society",
        },
        actor=owner,
    )
    service.add_exhibitor(
        owner,
        "fcos-2026",
        {
            "exhibitor_id": "ex-1",
            "display_name": "Grower One",
            "contact": {"email": "private@example.org"},
        },
        actor=owner,
    )
    service.add_entry_class(
        owner,
        "fcos-2026",
        {"class_id": "cattleya-species", "name": "Cattleya Species"},
        actor=owner,
    )
    service.add_entry(
        owner,
        "fcos-2026",
        {
            "entry_id": "entry-1",
            "exhibitor_id": "ex-1",
            "class_id": "cattleya-species",
            "entered_label_text": "Laelia anceps",
            "canonical_taxon_id": "taxon-laelia-anceps",
            "accepted_name_display": "Laelia anceps",
        },
        actor=owner,
    )
    service.add_judging_team(
        owner,
        "fcos-2026",
        {"team_id": "team-1", "judge_ids": ["judge-1", "judge-2"]},
        actor=owner,
    )


def test_entered_label_and_accepted_name_are_preserved_separately(tmp_path) -> None:
    service = _service(tmp_path)
    _seed(service)
    label = service.printable_entry_label("owner@example.org", "fcos-2026", "entry-1")
    assert label["entered_label_text"] == "Laelia anceps"
    assert label["accepted_name_display"] == "Laelia anceps"
    assert label["contains_private_contact"] is False


def test_awards_require_explicit_human_judging(tmp_path) -> None:
    service = _service(tmp_path)
    _seed(service)
    payload = {
        "decision_id": "decision-1",
        "entry_id": "entry-1",
        "team_id": "team-1",
        "decision_type": "ribbon",
        "award_name": "Blue Ribbon",
        "deciding_judge_ids": ["judge-1", "judge-2"],
        "rationale": "Human judges selected the entry.",
        "human_decision": False,
    }
    with pytest.raises(ValueError, match="HUMAN_JUDGING_DECISION_REQUIRED"):
        service.record_judging_decision(
            "owner@example.org", "fcos-2026", payload, actor="owner@example.org"
        )
    payload["human_decision"] = True
    decision = service.record_judging_decision(
        "owner@example.org", "fcos-2026", payload, actor="owner@example.org"
    )
    assert decision["human_decision"] is True
    assert decision["autonomous_award_authorized"] is False


def test_conflicts_require_recorded_resolution(tmp_path) -> None:
    service = _service(tmp_path)
    _seed(service)
    payload = {
        "decision_id": "decision-conflict",
        "entry_id": "entry-1",
        "team_id": "team-1",
        "decision_type": "ribbon",
        "award_name": "Blue Ribbon",
        "deciding_judge_ids": ["judge-1"],
        "rationale": "Human decision.",
        "human_decision": True,
        "conflicts": ["judge-1 is related to exhibitor"],
    }
    with pytest.raises(ValueError, match="JUDGING_CONFLICT_RESOLUTION_REQUIRED"):
        service.record_judging_decision(
            "owner@example.org", "fcos-2026", payload, actor="owner@example.org"
        )


def test_results_export_excludes_private_contact_and_payment_data(tmp_path) -> None:
    service = _service(tmp_path)
    _seed(service)
    export = service.results_export("owner@example.org", "fcos-2026")
    assert export["public_personal_data_included"] is False
    assert export["payment_data_included"] is False
    assert "contact" not in export["entries"][0]["exhibitor"]


def test_show_volunteer_assignment_reuses_private_volunteer_contract(tmp_path) -> None:
    service = _service(tmp_path)
    _seed(service)
    assignment = service.assign_volunteer(
        "owner@example.org",
        "fcos-2026",
        {
            "assignment_id": "show-vol-1",
            "volunteer_id": "vol-1",
            "role": "show table",
        },
        actor="owner@example.org",
    )
    assert assignment["volunteer_display_name"] == "Show Volunteer"
    assert assignment["binding_commitment_authorized"] is False


def test_owner_scope_and_readiness_boundaries(tmp_path) -> None:
    service = _service(tmp_path)
    _seed(service)
    with pytest.raises(FileNotFoundError):
        service.get_show("different-owner@example.org", "fcos-2026")
    readiness = service.readiness("owner@example.org", "fcos-2026")
    assert readiness["human_judging_required"] is True
    assert readiness["autonomous_awards_authorized"] is False
    assert readiness["payment_processing_authorized"] is False
    assert readiness["public_personal_data_authorized"] is False
    assert readiness["production_deployment_authorized"] is False
