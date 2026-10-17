"""FIL-001 contract invariants and agreement with the systems FIL extends."""

from __future__ import annotations

import ast
import json
from dataclasses import replace
from pathlib import Path

import jsonschema
import pytest

from app.functional_interaction.contracts import (
    CAPABILITY_STATUSES,
    EVIDENCE_STATES,
    SAFE_AUTONOMOUS_PERMISSIONS,
    AutonomyClass,
    BudgetRequirement,
    CapabilityDescriptor,
    ContractError,
    HealthSpec,
    OperatorClass,
    PortSpec,
)
from app.functional_interaction.ontology import (
    SEMANTIC_TYPES,
    is_subtype,
    lineage,
    require_type,
)
from app.functional_interaction.registry import FunctionalRegistry
from app.functional_interaction.scientific_demo import demo_descriptors, demo_registry
from app.provider_reservoir.capabilities import CAPABILITIES, CapabilityUnknown
from runtime.brain_capability_registry import CapabilityStatus

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads(
    (ROOT / "contracts" / "oc-fil-capability-descriptor.v1.json").read_text()
)


def _literal_assignment(path: Path, name: str) -> object:
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found in {path}")


def _base() -> CapabilityDescriptor:
    return demo_descriptors()[0]


def test_fifteen_operator_classes_exactly():
    assert [item.name for item in OperatorClass] == [
        "RECEPTOR",
        "SCANNER",
        "TRANSDUCER",
        "ENZYME",
        "TRANSPORTER",
        "ADAPTOR",
        "INTEGRATOR",
        "MODULATOR",
        "SWITCH",
        "OSCILLATOR",
        "BUFFER",
        "AMPLIFIER",
        "VALIDATOR",
        "INHIBITOR",
        "REPAIR_OPERATOR",
    ]
    assert SCHEMA["properties"]["operator_class"]["enum"] == [
        item.value for item in OperatorClass
    ]


def test_evidence_states_agree_with_research_traits_safe_states():
    safe_states = _literal_assignment(
        ROOT / "app" / "research_traits" / "service.py", "SAFE_STATES"
    )
    assert set(safe_states) == EVIDENCE_STATES


def test_safe_autonomous_permissions_agree_with_orchestrator_executable_policy_classes():
    executable = _literal_assignment(
        ROOT / "app" / "calyx_orchestrator" / "service.py", "EXECUTABLE_POLICY_CLASSES"
    )
    assert set(executable) == SAFE_AUTONOMOUS_PERMISSIONS


def test_status_vocabulary_is_the_brain_registry_vocabulary():
    from typing import get_args

    assert CAPABILITY_STATUSES == get_args(CapabilityStatus)
    assert SCHEMA["properties"]["health"]["properties"]["status"]["enum"] == list(
        CAPABILITY_STATUSES
    )
    assert [item.value for item in AutonomyClass] == ["A", "B", "C", "D"]


def test_unclassified_registry_capability_is_refused_by_the_routing_registry():
    with pytest.raises(CapabilityUnknown):
        replace(_base(), registry_capability="invented-capability")


def test_every_demo_descriptor_names_a_classified_capability_and_validates_against_schema():
    for descriptor in demo_descriptors():
        assert descriptor.registry_capability in CAPABILITIES
        jsonschema.validate(descriptor.to_dict(), SCHEMA)


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"version": "1.0"}, "INVALID_VERSION"),
        ({"capability_id": "NoDots"}, "INVALID_CAPABILITY_ID"),
        ({"summary": " "}, "SUMMARY_REQUIRED"),
        ({"effects": ("scientifically_published",)}, "FORBIDDEN_EFFECT"),
        ({"effects": ("Bad-Condition",)}, "INVALID_EFFECT"),
        ({"permissions": ("shell",)}, "CLASS_A_PERMISSION_NOT_SAFE"),
        (
            {"permissions": ("read_only_research", "read_only_research")},
            "DUPLICATE_PERMISSION",
        ),
        (
            {"budget": BudgetRequirement(provider_calls_max=1)},
            "DETERMINISTIC_CAPABILITY_HAS_PROVIDER_BUDGET",
        ),
        ({"emits": ("evidence.assertion.published",)}, "UNKNOWN_EMITTED_EVENT"),
        ({"triggers": ("cron",)}, "UNKNOWN_TRIGGER"),
        ({"inputs": ()}, "INPUTS_AND_OUTPUTS_REQUIRED"),
    ],
)
def test_descriptor_invariants_fail_closed(changes, code):
    with pytest.raises(ContractError, match=code):
        replace(_base(), **changes)


def test_automated_outputs_may_never_claim_verified():
    port = PortSpec("claims", "oc:ExtractedClaimBatch", ("VERIFIED", "PROVISIONAL"))
    with pytest.raises(ContractError, match="HUMAN_ONLY_EVIDENCE_STATE_ON_OUTPUT"):
        replace(_base(), outputs=(port,))


def test_unknown_evidence_state_and_semantic_type_spelling_are_refused():
    with pytest.raises(ContractError, match="UNKNOWN_EVIDENCE_STATE"):
        PortSpec("claims", "oc:ExtractedClaimBatch", ("FACT",))
    with pytest.raises(ContractError, match="INVALID_SEMANTIC_TYPE"):
        PortSpec("claims", "ExtractedClaimBatch", ("UNKNOWN",))
    with pytest.raises(ContractError, match="UNKNOWN_CAPABILITY_STATUS"):
        HealthSpec(status="GREEN")


def test_prohibited_permissions_only_describe_approval_or_prohibited_classes():
    with pytest.raises(
        ContractError, match="PROHIBITED_PERMISSION_REQUIRES_CLASS_B_OR_D"
    ):
        replace(
            _base(),
            permissions=("publish",),
            autonomy_class=AutonomyClass.PROPOSAL_ONLY,
        )
    prohibited = replace(
        _base(), permissions=("publish",), autonomy_class=AutonomyClass.PROHIBITED
    )
    assert prohibited.permissions == ("publish",)


def test_provider_capability_requires_provider_budget_and_is_never_class_a():
    explainer = next(d for d in demo_descriptors() if d.provider_required)
    with pytest.raises(
        ContractError, match="PROVIDER_CAPABILITY_NEEDS_PROVIDER_BUDGET"
    ):
        replace(explainer, budget=BudgetRequirement())
    with pytest.raises(ContractError, match="PROVIDER_CAPABILITY_CANNOT_BE_CLASS_A"):
        replace(explainer, autonomy_class=AutonomyClass.SAFE_AUTONOMOUS)


def test_ontology_is_single_rooted_and_subtyping_is_one_way():
    for name in SEMANTIC_TYPES:
        assert lineage(name)[-1] == "oc:Artifact"
    assert is_subtype("oc:ValidatedClaimBatch", "oc:ExtractedClaimBatch")
    assert not is_subtype("oc:ExtractedClaimBatch", "oc:ValidatedClaimBatch")
    with pytest.raises(ContractError, match="UNKNOWN_SEMANTIC_TYPE"):
        require_type("oc:Imagined")


def test_registry_rejects_duplicates_and_unknown_types():
    descriptor = _base()
    with pytest.raises(ContractError, match="DUPLICATE_CAPABILITY_ID"):
        FunctionalRegistry((descriptor, descriptor))
    unknown = replace(
        descriptor, inputs=(PortSpec("passages", "oc:Imagined", ("UNKNOWN",)),)
    )
    with pytest.raises(ContractError, match="UNKNOWN_SEMANTIC_TYPE"):
        FunctionalRegistry((unknown,))


def test_discovery_is_read_only_ordered_and_filterable():
    registry = demo_registry()
    view = registry.view()
    assert view["read_only"] is True
    assert view["execution_authority"] is False
    assert view["publication_authority"] is False
    ids = [item["capability_id"] for item in view["capabilities"]]
    assert ids == sorted(ids)
    assert [
        d.capability_id
        for d in registry.discover(operator_class=OperatorClass.VALIDATOR)
    ] == ["fil.evidence.candidate-validator"]
    assert [
        d.capability_id
        for d in registry.discover(produces="oc:TraitBankCandidateBatch")
    ] == ["fil.traitbank.candidate-buffer"]
    assert [
        d.capability_id
        for d in registry.discover(registry_capability="taxonomy-resolution")
    ] == ["fil.taxonomy.backbone-adaptor"]
    with pytest.raises(ContractError, match="UNKNOWN_FIL_CAPABILITY"):
        registry.get("fil.unknown.thing")


def test_brain_eligibility_is_consulted_not_restated_and_absence_fails_closed():
    linked = demo_registry().brain_eligibility("fil.reasoning.ledger-integrator")
    assert linked == {
        "capability_id": "reasoning_ledger",
        "eligible": True,
        "reasons": [],
    }
    assert demo_registry().brain_eligibility("fil.literature.claim-transducer") is None

    unsupplied = FunctionalRegistry(demo_descriptors())
    assert (
        unsupplied.brain_eligibility("fil.reasoning.ledger-integrator")["eligible"]
        is False
    )

    missing = FunctionalRegistry(
        (replace(_base(), brain_capability_id="not_in_brain"),),
        brain_registry=demo_registry()._brain_registry,
    )
    verdict = missing.brain_eligibility(_base().capability_id)
    assert verdict["eligible"] is False
    assert verdict["reasons"] == ["capability is absent from the verified registry"]
