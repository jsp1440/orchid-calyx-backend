from app.calyx_orchestrator.scientific_agents import SCIENTIFIC_ROLE_REGISTRY
from app.calyx_orchestrator.scientific_program import (
    CHIEF_SCIENTIST_JOB,
    SCIENTIFIC_JOB_TEMPLATES,
    SCIENTIFIC_PREREQUISITE_KEYS,
    build_scientific_program_fixture,
    scientific_mission_control_snapshot,
)


def test_phase_2_has_ten_domain_jobs_and_one_chief_scientist_job() -> None:
    fixture = build_scientific_program_fixture()

    assert len(SCIENTIFIC_JOB_TEMPLATES) == 10
    assert len(fixture["jobs"]) == 11
    assert len(SCIENTIFIC_ROLE_REGISTRY) == 11
    assert CHIEF_SCIENTIST_JOB.job_key == "chief_scientist_report"


def test_chief_scientist_depends_on_every_domain_job() -> None:
    fixture = build_scientific_program_fixture()
    chief = next(job for job in fixture["jobs"] if job["job_key"] == "chief_scientist_report")

    assert tuple(chief["depends_on"]) == SCIENTIFIC_PREREQUISITE_KEYS
    assert len(fixture["dependencies"]) == 10
    assert {edge["upstream"] for edge in fixture["dependencies"]} == set(SCIENTIFIC_PREREQUISITE_KEYS)
    assert {edge["downstream"] for edge in fixture["dependencies"]} == {"chief_scientist_report"}


def test_domain_jobs_are_ready_and_chief_scientist_waits() -> None:
    jobs = build_scientific_program_fixture()["jobs"]
    domain_jobs = [job for job in jobs if job["job_key"] != "chief_scientist_report"]
    chief = next(job for job in jobs if job["job_key"] == "chief_scientist_report")

    assert all(job["status"] == "ready" for job in domain_jobs)
    assert chief["status"] == "waiting"


def test_program_preserves_phase_1_concurrency_and_release_rules() -> None:
    fixture = build_scientific_program_fixture()

    assert fixture["max_active_jobs"] == 6
    assert fixture["release_rule"]["successful_outcomes"] == ["DELIVERED", "NO_OP"]
    assert fixture["release_rule"]["on_failed_prerequisite"] == "BLOCKED"
    assert fixture["release_rule"]["human_action_required"] is True


def test_every_template_declares_governance_and_outputs() -> None:
    jobs = build_scientific_program_fixture()["jobs"]

    for job in jobs:
        assert job["role"]
        assert job["domain"]
        assert job["policy_gate"]
        assert job["required_outputs"]


def test_scientific_safety_boundaries_fail_closed_in_contract() -> None:
    safety = build_scientific_program_fixture()["safety"]

    assert safety == {
        "automatic_merge": False,
        "production_deployment": False,
        "taxonomy_activation": False,
        "production_graph_mutation": False,
        "scientific_publication": False,
        "unlicensed_media_promotion": False,
    }


def test_mission_control_snapshot_exposes_roles_jobs_gates_and_human_actions() -> None:
    snapshot = scientific_mission_control_snapshot()

    assert snapshot["phase"] == 2
    assert snapshot["role_count"] == 11
    assert len(snapshot["roles"]) == 11
    assert len(snapshot["job_templates"]) == 11
    assert "activate_taxonomy" in snapshot["policy_gates"]
    assert "mutate_production_graph" in snapshot["policy_gates"]
    assert snapshot["human_actions"]
