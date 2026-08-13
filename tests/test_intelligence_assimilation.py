from app.intake.intelligence import (
    APPROVAL_REQUIRED_ACTIONS,
    assimilation_summary,
    canonical_email_text,
    intelligence_tasks,
    parse_external_intelligence,
)


TWIN_BRIEFING = """
Executive Summary — Top 5 Priorities
Google Earth Engine for orchid habitat surveillance
This executive-summary repetition should not create an item.

Research and Publications
Floral morphology changes behaviour of a shared orchid pollinator Medium Priority
A study reports that floral morphology changes pollinator behaviour.
Relevance: This may add pollinator and trait evidence.
Recommended Actions: Review the primary paper and compare its relationships with current evidence.
View Source →

Technology and Infrastructure Opportunities
Google Earth Engine for orchid habitat surveillance High Priority
Google Earth Engine can support satellite and remote sensing analysis of habitat, fire, moisture, and land-use change.
Relevance: It may extend Atlas environmental analysis.
Recommended Actions: Evaluate the platform and its datasets for noncommercial biodiversity work.
View Source →

Funding and Grants
EU LIFE 2026 Nature and Biodiversity call High Priority
The call has a deadline and requires eligibility checking.
Relevance: Potential conservation funding route.
Recommended Actions: Identify eligible partners before any submission or outreach.
View Source →
"""


def test_twin_briefing_is_decomposed_once_per_canonical_section():
    items = parse_external_intelligence(
        TWIN_BRIEFING,
        sender="twin@twin-mail.com",
        message_id="twin-2026-08-13",
    )

    assert len(items) == 3
    assert [item["domain"] for item in items] == ["research", "technology", "funding"]
    assert items[0]["title"] == "Floral morphology changes behaviour of a shared orchid pollinator"
    assert items[1]["title"] == "Google Earth Engine for orchid habitat surveillance"
    assert items[2]["title"] == "EU LIFE 2026 Nature and Biodiversity call"
    assert all(item["lifecycle"] == "DISCOVERED" for item in items)
    assert all(item["knowledge_delta"] == "UNASSESSED" for item in items)
    assert all(item["verification_required"] is True for item in items)


def test_domain_routing_connects_earth_engine_to_atlas_without_replacing_atlas():
    items = parse_external_intelligence(TWIN_BRIEFING)
    earth_engine = next(item for item in items if "Earth Engine" in item["title"])

    assert "atlas" in earth_engine["canonical_destinations"]
    assert "source_registry" in earth_engine["canonical_destinations"]
    assert "EVALUATE_ATLAS_PROVIDER" in earth_engine["follow_up_tasks"]
    assert "EVALUATE_FEDERATION" in earth_engine["follow_up_tasks"]
    assert earth_engine["canonical_graph_mutated"] is False
    assert earth_engine["external_contacted"] is False


def test_research_item_routes_pollinator_and_trait_evidence_to_canonical_domains():
    items = parse_external_intelligence(TWIN_BRIEFING)
    research = next(item for item in items if item["domain"] == "research")

    assert "orep" in research["canonical_destinations"]
    assert "pollinator_network" in research["canonical_destinations"]
    assert "traitbank" in research["canonical_destinations"]
    assert "EVALUATE_RELATIONSHIP_EVIDENCE" in research["follow_up_tasks"]


def test_funding_item_opens_eligibility_work_but_not_submission_or_outreach():
    items = parse_external_intelligence(TWIN_BRIEFING)
    funding = next(item for item in items if item["domain"] == "funding")

    assert funding["canonical_destinations"] == ["grant_intelligence"]
    assert "CHECK_GRANT_ELIGIBILITY" in funding["follow_up_tasks"]
    assert "grant_submission" in funding["approval_required_for"]
    assert "external_contact" in funding["approval_required_for"]
    assert funding["external_contacted"] is False


def test_email_provenance_is_part_of_canonical_content_and_hashable_identity():
    canonical = canonical_email_text(
        sender="twin@twin-mail.com",
        subject="Orchid Continuum Daily Briefing — Thursday, August 13, 2026",
        body="Funding and Grants\nExample High Priority\nDetails",
        message_id="abc123",
        received_at="2026-08-13T00:04:00-07:00",
    )

    assert "From: twin@twin-mail.com" in canonical
    assert "Message-ID: abc123" in canonical
    assert "Received-At: 2026-08-13T00:04:00-07:00" in canonical
    assert "X-Orchid-Intake-Kind: external-intelligence-email" in canonical


def test_follow_up_tasks_use_existing_intake_task_contract_and_fail_closed():
    items = parse_external_intelligence(TWIN_BRIEFING)
    tasks = intelligence_tasks(items)
    summary = assimilation_summary(items)

    assert tasks
    assert any(task.task_type == "verify_primary_source" for task in tasks)
    assert any(task.task_type == "compare_existing_knowledge" for task in tasks)
    assert any(task.task_type == "evaluate_atlas_provider" for task in tasks)
    assert summary["items_discovered"] == 3
    assert summary["external_contacted"] is False
    assert summary["canonical_graph_mutated"] is False
    assert summary["publication_performed"] is False
    assert "production_knowledge_graph_publication" in APPROVAL_REQUIRED_ACTIONS
