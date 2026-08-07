import pytest

import scripts.run_bounded_resumable_graph_dry_run as operator
from scripts.run_bounded_resumable_graph_dry_run import (
    build_evidence,
    choose_domain,
    require_preflight_ready,
    require_staging_only,
)

PREFLIGHT = {
    "contract": "calyx-graph-deployment-preflight-v3",
    "graph_mutation": False,
    "filesystem_mutation": False,
    "ready_for_live_resumable_dry_run": True,
    "blockers": [],
    "deployment": {"commit": "abc123"},
}


def test_choose_domain_prefers_taxonomy():
    assert choose_domain(["media", "taxonomy", "traits"]) == "taxonomy"


def test_choose_domain_uses_deterministic_fallback():
    assert choose_domain(["zeta", "alpha"]) == "alpha"


def test_choose_domain_accepts_explicit_ready_domain():
    assert choose_domain(["occurrences", "literature"], "literature") == "literature"


def test_choose_domain_rejects_explicit_unready_domain():
    with pytest.raises(ValueError, match="requested_domain_not_ready:media"):
        choose_domain(["occurrences", "literature"], "media")


def test_preflight_gate_accepts_exact_v3_contract():
    require_preflight_ready(dict(PREFLIGHT))


def test_preflight_gate_rejects_contract_mismatch():
    preflight = dict(PREFLIGHT)
    preflight["contract"] = "calyx-graph-deployment-preflight-v2"
    with pytest.raises(RuntimeError, match="deployment_preflight_contract_mismatch"):
        require_preflight_ready(preflight)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("graph_mutation", True, "graph_mutation_not_explicitly_false"),
        ("graph_mutation", None, "graph_mutation_not_explicitly_false"),
        ("filesystem_mutation", True, "filesystem_mutation_not_explicitly_false"),
        ("filesystem_mutation", None, "filesystem_mutation_not_explicitly_false"),
    ],
)
def test_preflight_gate_rejects_mutation_capability(field, value, message):
    preflight = dict(PREFLIGHT)
    if value is None:
        preflight.pop(field)
    else:
        preflight[field] = value
    with pytest.raises(RuntimeError, match=message):
        require_preflight_ready(preflight)


def test_preflight_gate_rejects_not_ready_with_blockers():
    preflight = dict(PREFLIGHT)
    preflight["ready_for_live_resumable_dry_run"] = False
    preflight["blockers"] = ["persistent_mount_missing"]
    with pytest.raises(RuntimeError, match="deployment_preflight_blocked"):
        require_preflight_ready(preflight)


def test_staging_gate_fails_closed_when_mutation_flag_missing():
    with pytest.raises(RuntimeError, match="production_graph_mutation_not_explicitly_false"):
        require_staging_only("report", {})


def test_build_evidence_fails_closed_on_publication():
    evidence = build_evidence(
        domain="taxonomy",
        session={"run_id": "RUN-1"},
        resume={"status": "paused"},
        report={"status": "paused"},
        preflight=PREFLIGHT,
        ready_domains=["taxonomy"],
    )
    assert evidence["schema_version"] == "2.0"
    assert evidence["action"] == "start_and_resume"
    assert evidence["bounds"] == {
        "batch_size": 100,
        "max_batches_per_step": 1,
        "domains": 1,
    }
    assert evidence["deployment"]["commit"] == "abc123"
    assert evidence["production_graph_mutation"] is False
    assert evidence["production_publication_authorized"] is False
    assert evidence["publication_endpoint_invoked"] is False
    assert len(evidence["artifact_hash"]) == 64


def test_resume_existing_advances_exactly_once_without_mutation_retry(monkeypatch):
    calls = []
    responses = iter(
        [
            (
                200,
                {
                    "production_graph_mutation": False,
                    "session": {
                        "run_id": "RUN-1",
                        "domains": ["occurrences"],
                        "status": "running",
                    },
                },
            ),
            (
                200,
                {
                    "production_graph_mutation": False,
                    "session": {"run_id": "RUN-1", "status": "completed"},
                },
            ),
            (
                200,
                {
                    "production_graph_mutation": False,
                    "session": {"run_id": "RUN-1", "status": "completed"},
                    "zero_delta": True,
                },
            ),
        ]
    )

    def fake_request(path, **kwargs):
        calls.append((path, kwargs))
        return next(responses)

    monkeypatch.setattr(operator, "request", fake_request)
    monkeypatch.setattr(operator, "SELECTED_DOMAIN", "occurrences")
    evidence = operator._resume_existing(
        token="token",
        preflight=PREFLIGHT,
        run_id="RUN-1",
    )
    assert evidence["action"] == "resume_existing"
    resume_calls = [item for item in calls if item[0].endswith("/resume")]
    assert len(resume_calls) == 1
    assert resume_calls[0][1]["method"] == "POST"
    assert resume_calls[0][1].get("retry_transient") is None


def test_resume_existing_rejects_completed_run_without_post(monkeypatch):
    calls = []

    def fake_request(path, **kwargs):
        calls.append((path, kwargs))
        return 200, {
            "production_graph_mutation": False,
            "session": {
                "run_id": "RUN-1",
                "domains": ["occurrences"],
                "status": "completed",
            },
        }

    monkeypatch.setattr(operator, "request", fake_request)
    monkeypatch.setattr(operator, "SELECTED_DOMAIN", "")
    with pytest.raises(RuntimeError, match="existing_run_already_completed"):
        operator._resume_existing(
            token="token",
            preflight=PREFLIGHT,
            run_id="RUN-1",
        )
    assert len(calls) == 1
