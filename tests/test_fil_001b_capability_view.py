"""FIL-001B: one canonical capability view, and declaration to the existing router."""

from __future__ import annotations

import copy

import pytest

from app.functional_interaction.capability_view import (
    _CROSSWALKS,
    BRAIN_CAPABILITY_CROSSWALK,
    CANONICAL_SOURCE,
    Crosswalk,
    CrosswalkError,
    _live_vocabularies,
    canonical_capability_view,
    require_canonical,
)
from app.functional_interaction.literature_to_calyx import chain_descriptors, plan_chain
from app.functional_interaction.planner import SourceArtifact, plan_workflow
from app.functional_interaction.scientific_demo import demo_descriptors, demo_registry
from app.functional_interaction.work_declaration import declaration_body, route_plan
from app.provider_reservoir.capabilities import CAPABILITIES, CapabilityUnknown

ALL = (*demo_descriptors(), *chain_descriptors())


def test_view_is_keyed_by_the_routing_registry_and_read_only():
    view = canonical_capability_view(ALL)
    assert view["canonical_source"] == CANONICAL_SOURCE
    assert [row["name"] for row in view["capabilities"]] == sorted(CAPABILITIES)
    assert view["read_only"] is True and view["execution_authority"] is False


def test_every_live_vocabulary_member_is_mapped_or_explicitly_unmapped():
    view = canonical_capability_view(ALL)
    live = _live_vocabularies()
    for vocabulary, members in live.items():
        unmapped = {item["member"] for item in view["unmapped"].get(vocabulary, [])}
        mapped = view["coverage"][vocabulary]["mapped"]
        assert mapped + len(unmapped) == len(members)
        for item in view["unmapped"].get(vocabulary, []):
            assert item["reason"].strip()


def test_coverage_reports_the_real_gaps():
    coverage = canonical_capability_view(ALL)["coverage"]
    # Four engineering roles map to no scientific capability; #1813's TraitBank
    # batch validator, once live, maps to schema-validation.
    if "traitbank_batch_validator" in _live_vocabularies()["executor_roles"]:
        assert coverage["executor_roles"] == {"members": 5, "mapped": 1}
    else:
        assert coverage["executor_roles"] == {"members": 4, "mapped": 0}
    assert coverage["brain_capabilities"] == {"members": 6, "mapped": 2}
    assert coverage["canonical_with_fil_descriptor"]["members"] == len(CAPABILITIES)


def test_new_vocabulary_member_without_crosswalk_is_refused():
    live = _live_vocabularies()
    live["executor_roles"] = (*live["executor_roles"], "new_unclassified_role")
    with pytest.raises(
        CrosswalkError, match="UNMAPPED:executor_roles:new_unclassified_role"
    ):
        canonical_capability_view(ALL, live=live)


def test_stale_crosswalk_entry_and_unknown_canonical_name_are_refused():
    crosswalks = copy.deepcopy(_CROSSWALKS)
    crosswalks["brain_capabilities"] = {
        **BRAIN_CAPABILITY_CROSSWALK,
        "retired_capability": Crosswalk((), "gone"),
        "data_intelligence": Crosswalk(("tabular-wizardry",), "invented"),
    }
    with pytest.raises(CrosswalkError) as raised:
        canonical_capability_view(ALL, crosswalks=crosswalks)
    assert "STALE_CROSSWALK_ENTRY:brain_capabilities:retired_capability" in str(
        raised.value
    )
    assert (
        "UNKNOWN_CANONICAL:brain_capabilities:data_intelligence:tabular-wizardry"
        in str(raised.value)
    )


def test_fil_brain_link_must_agree_with_the_crosswalk():
    crosswalks = copy.deepcopy(_CROSSWALKS)
    crosswalks["brain_capabilities"] = {
        **BRAIN_CAPABILITY_CROSSWALK,
        "literature_candidate_handoff": Crosswalk(
            ("literature-evidence-lookup",), "narrowed"
        ),
    }
    with pytest.raises(
        CrosswalkError, match="FIL_BRAIN_LINK_DISAGREES:fil.calyx.verification-handoff"
    ):
        canonical_capability_view(ALL, crosswalks=crosswalks)


def test_recorded_mirror_drift_is_still_canonical():
    rows = {row["name"]: row for row in canonical_capability_view(ALL)["capabilities"]}
    assert rows["firecrawl-acquisition"]["mirror_drift"]
    assert rows["firecrawl-acquisition"]["provider_required"] is True
    with pytest.raises(CapabilityUnknown):
        require_canonical("firecrawl")


def test_chain_declares_to_the_existing_router_and_no_lane_is_enabled():
    routed = route_plan(plan_chain(), issue_number=0)
    assert routed["provider_free"] is True
    assert routed["blocking_provider_capabilities"] == []
    assert routed["lane_executable"] is False
    assert "open-ended-code-authoring" in routed["unexecutable_reason"]
    assert routed["issue_created"] is False and routed["lease_claimed"] is False


def test_provider_plan_routes_as_provider_blocked():
    from dataclasses import replace

    from app.functional_interaction.contracts import HealthSpec
    from app.functional_interaction.registry import FunctionalRegistry

    descriptors = [
        replace(d, health=HealthSpec(status="PARTIAL")) if d.provider_required else d
        for d in demo_descriptors()
    ]
    plan = plan_workflow(
        FunctionalRegistry(tuple(descriptors)),
        source=SourceArtifact(
            "oc:LiteraturePassageBatch", ("UNKNOWN",), ("source_anchored",)
        ),
        goal_type="oc:PlainLanguageExplanation",
        no_api_mode=False,
    )
    routed = route_plan(plan)
    assert routed["blocking_provider_capabilities"] == ["natural-language-explanation"]
    assert routed["provider_free"] is False


def test_declaration_refuses_an_empty_plan():
    plan = plan_workflow(
        demo_registry(),
        source=SourceArtifact("oc:LiteraturePassageBatch", ("UNKNOWN",)),
        goal_type="oc:ReasoningDraft",
    )
    with pytest.raises(ValueError, match="NO_PLAN_TO_DECLARE"):
        declaration_body(plan)


def test_pending_member_is_not_stale_before_its_pr_and_is_checked_after():
    from app.functional_interaction.capability_view import PENDING_MEMBERS

    assert ("executor_roles", "traitbank_batch_validator") in PENDING_MEMBERS
    live = _live_vocabularies()
    before = canonical_capability_view(ALL, live=live)
    pending_live = "traitbank_batch_validator" in live["executor_roles"]
    if not pending_live:
        live = {
            **live,
            "executor_roles": (*live["executor_roles"], "traitbank_batch_validator"),
        }
    after = canonical_capability_view(ALL, live=live)
    rows = {row["name"]: row for row in after["capabilities"]}
    assert "traitbank_batch_validator" in rows["schema-validation"]["executor_roles"]
    assert after["coverage"]["executor_roles"]["mapped"] == before["coverage"][
        "executor_roles"
    ]["mapped"] + (0 if pending_live else 1)
