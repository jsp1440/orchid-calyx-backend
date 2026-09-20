"""Provider-free contract tests for the cross-repository work record."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.oc_federation_state import build_backend_completion, validate_work_record

SHA = "a" * 40


def record() -> dict:
    return build_backend_completion(
        repository="jsp1440/orchid-calyx-backend",
        work_id="backend:integration:6349ac5d",
        integration_sha=SHA,
        verification_sha=SHA,
        run_id="123",
        run_attempt="1",
        capabilities=["schema-validation", "test-execution"],
        downstream_dependents=[{
            "work_id": "frontend:queue-probe",
            "repository": "jsp1440/orchid-continuum-frontend",
            "issue": 703,
            "capability": "test-execution",
        }],
    )


def test_record_contains_the_complete_exact_head_handoff():
    value = record()
    assert value["schema"] == "oc.federation-work-record.v1"
    assert value["state"] == "settled"
    assert value["provider_requirement"] is False
    assert value["owner_gate"] is False
    assert value["settlement"]["provider_calls"] == 0
    assert value["downstream_dependents"][0]["repository"].endswith("frontend")
    assert validate_work_record(value) is value


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("implementation_sha", "not-a-sha", "implementation_sha_invalid"),
        ("state", "settled", "settled_record_without_settlement"),
        ("block_reason", "owner_gate", "owner_gate_mismatch"),
        ("repository", "frontend", "repository_invalid"),
    ],
)
def test_invalid_or_misleading_records_fail_closed(field, value, error):
    candidate = record()
    if field == "state":
        candidate["settlement"]["state"] = "pending"
    elif field == "block_reason":
        candidate["state"] = "blocked"
    candidate[field] = value
    with pytest.raises(ValueError, match=error):
        validate_work_record(candidate)


def test_provider_required_work_can_be_waiting_but_never_claims_settlement():
    candidate = record()
    candidate.update({
        "state": "blocked",
        "block_reason": "external_provider",
        "provider_requirement": True,
        "settlement": {"state": "pending"},
        "owner_gate": False,
    })
    assert validate_work_record(candidate)["state"] == "blocked"


def test_contract_file_declares_every_field_the_validator_requires():
    contract = json.loads((Path(__file__).parents[1] / "contracts/oc-federation-v1.json").read_text())
    assert contract["schema"] == "oc.federation-work-record.v1"
    assert set(contract["required"]) == set(record()) - {"schema"}
