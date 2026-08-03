from scripts.check_oc_parallel_contract import compare_contracts  # noqa: I001


CANONICAL = {
    "contract_version": "oc-parallel-v1",
    "routes": {
        "GET /api/platform/homepage": {
            "response_required": ["contract_version", "sections"],
        }
    },
    "enums": {"availability": ["available", "degraded", "unavailable"]},
    "governance": {"client_scoring_allowed": False},
}


def test_additive_candidate_contract_is_compatible():
    candidate = {
        "contract_version": "oc-parallel-v1",
        "routes": {
            "GET /api/platform/homepage": {
                "response_required": ["contract_version", "sections", "generated_at"],
            }
        },
        "enums": {"availability": ["available", "degraded", "unavailable", "pending"]},
        "governance": {"client_scoring_allowed": False},
    }
    assert compare_contracts(CANONICAL, candidate) == []


def test_missing_required_field_is_incompatible():
    candidate = {
        "contract_version": "oc-parallel-v1",
        "routes": {"GET /api/platform/homepage": {"response_required": ["contract_version"]}},
        "enums": {"availability": ["available", "degraded", "unavailable"]},
        "governance": {"client_scoring_allowed": False},
    }
    assert "missing_response_required:GET /api/platform/homepage:sections" in compare_contracts(
        CANONICAL, candidate
    )


def test_governance_relaxation_is_incompatible():
    candidate = {
        **CANONICAL,
        "governance": {"client_scoring_allowed": True},
    }
    assert compare_contracts(CANONICAL, candidate) == ["governance_mismatch:client_scoring_allowed"]
