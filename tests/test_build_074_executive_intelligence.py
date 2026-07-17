from app.executive_intelligence.engine import (
    ProviderCandidate,
    build_recommendations,
    choose_provider,
    evaluate_budget,
)


def test_new_species_paper_generates_taxonomy_and_literature_recommendations():
    items = build_recommendations({"id": 7, "title": "A new species paper", "content": "sp. nov. DOI 10.1/test"})
    kinds = {item["recommendation_type"] for item in items}
    assert "NEW_TAXON_REVIEW" in kinds
    assert "LITERATURE_EXTRACTION" in kinds
    assert all(item["evidence"]["source_id"] == 7 for item in items)


def test_general_intake_still_gets_review_without_mutation_instruction():
    items = build_recommendations({"id": 9, "title": "Unclassified note", "content": "miscellaneous observation"})
    assert [item["recommendation_type"] for item in items] == ["GENERAL_REVIEW"]
    assert items[0]["proposed_action_type"] == "TASK"


def test_budget_hard_limit_blocks():
    result = evaluate_budget(spent_usd=9.5, proposed_usd=1.0, soft_limit_usd=8, hard_limit_usd=10)
    assert result["decision"] == "BLOCK"
    assert result["projected_spend_usd"] == 10.5


def test_budget_soft_limit_can_downgrade():
    result = evaluate_budget(spent_usd=7, proposed_usd=2, soft_limit_usd=8, hard_limit_usd=20, policy_mode="DOWNGRADE")
    assert result["decision"] == "DOWNGRADE"


def test_provider_router_prefers_priority_normally_and_cost_when_downgraded():
    providers = [
        ProviderCandidate("premium", frozenset({"reasoning"}), priority=1, cost_rank=10),
        ProviderCandidate("economy", frozenset({"reasoning"}), priority=5, cost_rank=1),
    ]
    normal = choose_provider(capability="reasoning", providers=providers)
    economy = choose_provider(capability="reasoning", providers=providers, budget_decision="DOWNGRADE")
    assert normal["selected"] == "premium"
    assert economy["selected"] == "economy"
    assert economy["fallbacks"] == ["premium"]


def test_unhealthy_and_incapable_providers_are_excluded():
    providers = [
        ProviderCandidate("down", frozenset({"vision"}), priority=1, cost_rank=1, healthy=False),
        ProviderCandidate("wrong", frozenset({"coding"}), priority=1, cost_rank=1),
    ]
    result = choose_provider(capability="vision", providers=providers)
    assert result["selected"] is None
    assert result["fallbacks"] == []
