from collections import Counter

from app.lexicon.intake import (
    EXPECTED_FIELDS,
    filter_items,
    get_item,
    load_items,
    validate_manifest,
)
from app.lexicon.intake_routes import intake_status, list_intake_items, read_intake_item
from app.routers.calyx_core import router as calyx_core_router

AUTH = {"actor": "owner", "auth_type": "owner_session"}


def test_manifest_decodes_to_exact_workbook_reconciliation_counts():
    rows = load_items()
    assert len(rows) == 420
    assert tuple(rows[0].keys()) == EXPECTED_FIELDS
    assert len({row["glossary_id"] for row in rows}) == 420

    definition_counts = Counter(row["definition_state"] for row in rows)
    concept_counts = Counter(row["concept_intake_state"] for row in rows)
    figure_exists_counts = Counter(row["figure_exists"] for row in rows)
    figure_state_counts = Counter(row["figure_state"] for row in rows)

    assert definition_counts == {"PRESENT": 221, "PLACEHOLDER": 199}
    assert concept_counts == {"READY_FOR_CONCEPT_REVIEW": 221, "BLOCKED_DEFINITION": 199}
    assert figure_exists_counts == {"NO": 383, "PROBABLE / VERIFY": 27, "YES": 10}
    assert figure_state_counts == {
        "FIGURE_GENERATION_HOLD": 383,
        "PROBABLE_ASSET_VERIFY": 27,
        "EXISTING_ASSET_VERIFY": 10,
    }


def test_existing_or_probable_assets_do_not_bypass_definition_quality_gate():
    rows = load_items()
    covered = [row for row in rows if row["figure_exists"] != "NO"]
    assert len(covered) == 37
    assert all(row["definition_state"] == "PLACEHOLDER" for row in covered)
    assert all(row["concept_intake_state"] == "BLOCKED_DEFINITION" for row in covered)


def test_manifest_status_is_provenance_locked_and_nonpublishing():
    status = validate_manifest()
    assert status["valid"] is True
    assert status["source_sha256"] == "fe0dfed4e6cd5e330ccba94967b4541f475389bb89065479ea2296fdce83e687"
    assert status["summary"]["terms"] == 420
    assert status["policy"]["placeholder_definitions_block_import"] is True
    assert status["policy"]["figure_generation_hold_until_calyx_vision_review"] is True
    assert status["policy"]["automatic_concept_promotion"] is False
    assert status["policy"]["automatic_publication"] is False


def test_filtering_and_lookup_are_deterministic():
    blocked_priority_zero = filter_items(
        concept_intake_state="BLOCKED_DEFINITION",
        priority=0,
        limit=500,
    )
    assert blocked_priority_zero
    assert all(row["concept_intake_state"] == "BLOCKED_DEFINITION" for row in blocked_priority_zero)
    assert all(row["priority"] == 0 for row in blocked_priority_zero)

    anther = get_item("T0014")
    assert anther is not None
    assert anther["term"] == "anther cap"
    assert anther["concept_intake_state"] == "BLOCKED_DEFINITION"


def test_read_only_routes_expose_status_items_and_item_detail():
    status = intake_status(AUTH)
    assert status["valid"] is True

    result = list_intake_items(
        AUTH,
        q="resupination",
        concept_intake_state=None,
        figure_state=None,
        priority=None,
        limit=100,
    )
    assert result["read_only"] is True
    assert result["total_manifest_items"] == 420
    assert any(item["term"].casefold() == "resupination" for item in result["items"])

    detail = read_intake_item("T0014", AUTH)
    assert detail["read_only"] is True
    assert detail["item"]["term"] == "anther cap"


def test_intake_routes_are_mounted_under_canonical_api():
    paths = {getattr(route, "path", "") for route in calyx_core_router.routes}
    assert "/api/lexicon/intake/status" in paths
    assert "/api/lexicon/intake/items" in paths
    assert "/api/lexicon/intake/items/{glossary_id}" in paths
