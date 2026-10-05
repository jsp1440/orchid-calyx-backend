import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.cognitive_integration.executor import CognitiveIntegrationError
from app.provider_reservoir.routing import route_task
from scripts import oc_brain_pulse as brain_pulse
from scripts import (
    oc_provider_free_validate,
    oc_swarm_provider_free_worker,
    oc_work_materialize,
)
from scripts.oc_brain_pulse import (
    CALYX_PRODUCT_SOURCE,
    MISSION_SOURCE,
    SOURCE,
    build_report,
    calyx_product_materialization_report,
    fingerprint,
    main,
    mission_gap_candidates,
    source_registry_gap_candidates,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC_INTEGRATION_REF = "synthetic-test-fixture-not-an-observed-sha"


def _product_only_report(monkeypatch):
    monkeypatch.setattr(brain_pulse, "mission_gap_candidates", list)
    monkeypatch.setattr(brain_pulse, "source_registry_gap_candidates", list)
    monkeypatch.setattr(brain_pulse, "SUPPORTED_QUESTIONS", ())
    return build_report()


def test_brain_pulse_is_provider_free_and_non_authoritative():
    report = build_report()
    assert report["schema"] == "oc.work-discovery.v1"
    assert report["source"] == SOURCE
    assert report["authority"] == {
        "may_queue_research_or_engineering_work": True,
        "may_call_provider": False,
        "may_modify_governance": False,
        "may_promote_hypothesis": False,
        "may_activate_scientific_conclusion": False,
    }


def test_brain_pulse_emits_deduplicable_governed_candidates():
    report = build_report()
    assert report["candidate_count"] > 0
    assert report["candidate_count"] == len(report["candidates"])
    fingerprints = [candidate["fingerprint"] for candidate in report["candidates"]]
    assert len(fingerprints) == len(set(fingerprints))
    for candidate in report["candidates"]:
        assert "oc-queued" in candidate["labels"]
        assert "oc-discovered" in candidate["labels"]
        assert candidate["source"] in {
            SOURCE,
            MISSION_SOURCE,
            "brain-source-contract-gap",
            CALYX_PRODUCT_SOURCE,
        }
        assert candidate["validation_command"] == ""
        assert candidate["capabilities"] == []


def test_brain_fingerprint_changes_only_when_material_identity_changes():
    base = fingerprint("q", "missing_evidence", "gap")
    assert base == fingerprint("q", "missing_evidence", "gap")
    assert base != fingerprint("q2", "missing_evidence", "gap")
    assert base != fingerprint("q", "missing_source", "gap")
    assert base != fingerprint("q", "missing_evidence", "different")


def test_brain_pulse_records_cognitive_integration_errors(monkeypatch):
    monkeypatch.setattr(brain_pulse, "SUPPORTED_QUESTIONS", ("question",))

    def fail_execution(_question):
        raise CognitiveIntegrationError("reasoning map unavailable")

    monkeypatch.setattr(brain_pulse, "execute", fail_execution)

    report = build_report()

    assert report["questions_evaluated"] == []
    assert report["errors"] == [
        {"question": "question", "error": "CognitiveIntegrationError"}
    ]


def test_brain_pulse_does_not_suppress_unexpected_errors(monkeypatch):
    monkeypatch.setattr(brain_pulse, "SUPPORTED_QUESTIONS", ("question",))

    def fail_execution(_question):
        raise RuntimeError("unexpected implementation failure")

    monkeypatch.setattr(brain_pulse, "execute", fail_execution)

    with pytest.raises(RuntimeError, match="unexpected implementation failure"):
        build_report()


def test_calyx_product_is_materializable_even_when_brain_candidates_fill_the_cap(monkeypatch):
    report = _product_only_report(monkeypatch)
    calyx_candidate = next(
        candidate
        for candidate in report["candidates"]
        if candidate["source"] == CALYX_PRODUCT_SOURCE
    )
    assert CALYX_PRODUCT_SOURCE in report["sources_evaluated"]
    assert calyx_candidate["lane"] == "university-education"
    assert calyx_candidate["requires_human_review"] is True
    assert calyx_candidate["scientific_effect"] == "none"

    competing = [
        {
            **calyx_candidate,
            "fingerprint": f"{index:016x}",
            "rank": 1,
            "source": "brain-reasoning-gap",
            "title": f"[Brain] higher-ranked candidate {index}",
        }
        for index in (1, 2)
    ]
    crowded = {
        **report,
        "candidates": [*competing, *report["candidates"]],
    }
    ordinary_plan = oc_work_materialize.plan(
        crowded, {}, max_new=2
    )
    product_report = calyx_product_materialization_report(report)
    reserved_plan = oc_work_materialize.plan(
        product_report, {}, max_new=1
    )

    assert calyx_candidate["fingerprint"] in {
        action["fingerprint"] for action in ordinary_plan["actions"]
    }
    assert len(ordinary_plan["actions"]) == 3
    assert [action["fingerprint"] for action in reserved_plan["actions"]] == [
        calyx_candidate["fingerprint"]
    ]


def test_calyx_product_validation_passes_with_an_explicit_no_action(monkeypatch, capsys):
    module = {**brain_pulse.AppliedAIDataScienceService.module(), "reading_level": "grade-10"}
    monkeypatch.setattr(
        brain_pulse.AppliedAIDataScienceService,
        "module",
        staticmethod(lambda: module),
    )
    monkeypatch.setattr(
        "sys.argv",
        ["oc_brain_pulse", "--verify-calyx-product"],
    )

    assert main() == 0
    verification = json.loads(capsys.readouterr().out)
    assert verification["passed"] is True
    assert verification["outcome"] == "no_action"
    assert verification["finding_kinds"] == ["no_action"]
    assert verification["candidate_count"] == 0


def test_calyx_finding_runs_through_materialization_validation_and_owner_settlement(
    monkeypatch,
):
    report = _product_only_report(monkeypatch)
    product_report = calyx_product_materialization_report(report)
    planned = oc_work_materialize.plan(product_report, {}, max_new=1)
    assert planned["action_count"] == 1
    action = planned["actions"][0]
    body = action["body"]
    issue = {"number": 2180, "state": "OPEN", "body": body}

    routing = route_task(issue)
    assert routing.lane_executable is True
    assert routing.executable_task == "validate"
    execution = oc_swarm_provider_free_worker.execution_plan(issue)
    assert execution["supported"] is True
    assert execution["commands"] == ["calyx-product-advisory"]

    command = oc_provider_free_validate._COMMANDS.resolve(execution["commands"])[0]

    def run_registered_command(argv, cwd, timeout):
        assert argv == command.argv
        return subprocess.run(
            [sys.executable, *argv[1:]],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    validation = oc_provider_free_validate.run_validation(
        execution["commands"],
        cwd=str(REPO_ROOT),
        runner=run_registered_command,
    )
    assert validation["passed"] is True
    verified_operation = json.loads(validation["results"][0]["output_tail"])
    assert verified_operation["artifact_id"] == report["calyx_product"]["artifact_id"]
    assert verified_operation["receipt"]["passed"] is True
    assert verified_operation["candidate_count"] == 1

    lease = (
        '[OC-SWARM-V4] Dependency/resource lease claimed: '
        '`{"reads":["control-plane"],"writes":[]}`.'
    )
    receipt = oc_swarm_provider_free_worker.build_receipt(
        issue,
        lease_comment=lease,
        changed_files=[],
        integration_sha=SYNTHETIC_INTEGRATION_REF,
        validation=validation,
    )
    assert receipt["mode"] == "validate"
    assert receipt["integration_sha"] == SYNTHETIC_INTEGRATION_REF
    assert receipt["disposition"] == "owner-gate"
    assert receipt["validation"]["passed"] is True
    assert receipt["safety"]["provider_calls"] is False
    assert receipt["safety"]["scientific_mutation"] is False

    filed = oc_work_materialize.FiledIssue(
        number=issue["number"],
        state="OPEN",
        state_reason="",
        labels=frozenset({"oc-discovered", "oc-owner-gate"}),
        body=body,
    )
    replenished = oc_work_materialize.plan(
        product_report,
        {action["fingerprint"]: [filed]},
        max_new=1,
    )
    assert replenished["action_count"] == 0
    assert replenished["skipped"][0]["reason"] == "owner_hold"


def test_brain_pulse_writes_a_separate_calyx_materialization_report(tmp_path, monkeypatch):
    pulse_path = tmp_path / "brain-pulse.json"
    product_path = tmp_path / "calyx-product-pulse.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "oc_brain_pulse",
            "--output",
            str(pulse_path),
            "--calyx-product-output",
            str(product_path),
        ],
    )

    _product_only_report(monkeypatch)
    assert main() == 0
    pulse = json.loads(pulse_path.read_text(encoding="utf-8"))
    product = json.loads(product_path.read_text(encoding="utf-8"))
    assert pulse["calyx_product"]["receipt"]["passed"] is True
    assert product["source"] == CALYX_PRODUCT_SOURCE
    assert product["status"] == "ready"
    assert product["sources_evaluated"] == [CALYX_PRODUCT_SOURCE]
    assert product["candidate_count"] == len(product["candidates"])
    assert product["receipt"]["passed"] is True
    assert all(
        candidate["source"] == CALYX_PRODUCT_SOURCE for candidate in product["candidates"]
    )


def test_calyx_failure_blocks_only_calyx_and_preserves_brain_materialization(
    tmp_path, monkeypatch, capsys
):
    brain_candidate = mission_gap_candidates()[0]
    pulse_path = tmp_path / "brain-pulse.json"
    product_path = tmp_path / "calyx-product-pulse.json"
    monkeypatch.setattr(brain_pulse, "mission_gap_candidates", lambda: [brain_candidate])
    monkeypatch.setattr(brain_pulse, "source_registry_gap_candidates", list)
    monkeypatch.setattr(brain_pulse, "SUPPORTED_QUESTIONS", ())

    def fail_calyx():
        raise RuntimeError("CALYX_PRODUCT_RECEIPT_FAILED")

    monkeypatch.setattr(brain_pulse, "calyx_product_operation", fail_calyx)
    monkeypatch.setattr(
        "sys.argv",
        [
            "oc_brain_pulse",
            "--output",
            str(pulse_path),
            "--calyx-product-output",
            str(product_path),
        ],
    )

    assert main() == 0
    pulse = json.loads(pulse_path.read_text(encoding="utf-8"))
    product = json.loads(product_path.read_text(encoding="utf-8"))

    assert pulse["calyx_product"] == {
        "status": "blocked",
        "error": {
            "code": "RuntimeError",
            "detail": "CALYX_PRODUCT_RECEIPT_FAILED",
        },
    }
    assert {
        "source": CALYX_PRODUCT_SOURCE,
        "error": "RuntimeError",
        "detail": "CALYX_PRODUCT_RECEIPT_FAILED",
    } in pulse["errors"]
    assert CALYX_PRODUCT_SOURCE not in pulse["sources_evaluated"]
    assert pulse["candidates"] == [brain_candidate]
    assert product["status"] == "blocked"
    assert "candidate_count" not in product
    assert "candidates" not in product
    assert product["errors"] == [
        {
            "source": CALYX_PRODUCT_SOURCE,
            "code": "RuntimeError",
            "detail": "CALYX_PRODUCT_RECEIPT_FAILED",
        }
    ]

    brain_plan = oc_work_materialize.plan(pulse, {}, max_new=1)
    assert [action["fingerprint"] for action in brain_plan["actions"]] == [
        brain_candidate["fingerprint"]
    ]
    with pytest.raises(
        oc_work_materialize.CalyxProductReportBlocked,
        match="CALYX_PRODUCT_REPORT_BLOCKED",
    ):
        oc_work_materialize.plan(product, {}, max_new=1)

    product_report_path = tmp_path / "blocked-calyx-product.json"
    product_report_path.write_text(json.dumps(product), encoding="utf-8")

    def unexpected_github_call(*_args, **_kwargs):
        raise AssertionError("blocked Calyx materialization must not contact GitHub")

    monkeypatch.setattr(oc_work_materialize, "github", unexpected_github_call)
    assert (
        oc_work_materialize.main(
            [
                "--repository",
                "jsp1440/orchid-calyx-backend",
                "--report",
                str(product_report_path),
                "--apply",
            ]
        )
        == 2
    )
    refusal = json.loads(capsys.readouterr().out)
    assert refusal["status"] == "blocked"
    assert refusal["source"] == CALYX_PRODUCT_SOURCE
    assert refusal["errors"] == product["errors"]


def test_mission_gap_observer_uses_only_explicit_safe_blocks():
    candidates = mission_gap_candidates()
    assert candidates
    assert {candidate["source"] for candidate in candidates} == {MISSION_SOURCE}
    titles = {candidate["title"] for candidate in candidates}
    assert any("source registry refresh" in title for title in titles)
    assert any("literature ingestion review" in title for title in titles)
    for candidate in candidates:
        assert "not_implemented_safe_block" in candidate["summary"]
        assert candidate["validation_command"] == ""
        assert candidate["capabilities"] == []



def test_source_registry_observer_queues_only_disabled_explicit_contracts():
    candidates = source_registry_gap_candidates()
    assert candidates
    assert {candidate["source"] for candidate in candidates} == {"brain-source-contract-gap"}
    titles = {candidate["title"] for candidate in candidates}
    assert any("habitat" in title for title in titles)
    assert any("education" in title for title in titles)
    for candidate in candidates:
        assert "disabled fail-closed" in candidate["summary"]
        assert "invented data" in candidate["summary"]
