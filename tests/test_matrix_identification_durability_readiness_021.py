from runtime.matrix_identification_durability_readiness import (
    compose_matrix_durability_readiness,
)


def _session_preflight(*, ready: bool, blockers=None):
    return {
        "migration_612_schema_ready": ready,
        "activation_ready": ready,
        "blockers": blockers or [],
    }


def _registry_preflight(*, ready: bool, blockers=None):
    return {
        "migration_613_schema_ready": ready,
        "source_inventory_ready": ready,
        "data_copy_ready": ready,
        "activation_ready": ready,
        "blockers": blockers or [],
    }


def _status(*, active: bool):
    return {"durable": active, "ready": active}


def test_scientific_trail_ready_requires_both_session_and_registry_readiness():
    result = compose_matrix_durability_readiness(
        session_preflight=_session_preflight(ready=True),
        registry_preflight=_registry_preflight(ready=False, blockers=["MATRIX_REGISTRY_VERSIONS_MISSING_IN_DATABASE"]),
        session_status=_status(active=False),
        registry_status=_status(active=False),
    )

    assert result["scientific_trail_activation_ready"] is False
    assert result["scientific_trail_durable_active"] is False
    assert result["blockers"] == [
        {"component": "registry", "code": "MATRIX_REGISTRY_VERSIONS_MISSING_IN_DATABASE"}
    ]


def test_full_durable_active_requires_both_stores_active():
    result = compose_matrix_durability_readiness(
        session_preflight=_session_preflight(ready=True),
        registry_preflight=_registry_preflight(ready=True),
        session_status=_status(active=True),
        registry_status=_status(active=False),
    )

    assert result["scientific_trail_activation_ready"] is True
    assert result["scientific_trail_durable_active"] is False
    assert result["components"]["session"]["durable_active"] is True
    assert result["components"]["registry"]["durable_active"] is False


def test_deployment_sequence_never_claims_to_perform_mutations():
    result = compose_matrix_durability_readiness(
        session_preflight=_session_preflight(ready=False, blockers=["MATRIX_SESSION_SCHEMA_NOT_READY"]),
        registry_preflight=_registry_preflight(ready=False, blockers=["MATRIX_REGISTRY_SCHEMA_NOT_READY"]),
        session_status=_status(active=False),
        registry_status=_status(active=False),
    )

    assert result["automatic_migration"] is False
    assert result["automatic_data_copy"] is False
    assert result["automatic_environment_change"] is False
    assert all(step["performed_by_readiness"] is False for step in result["deployment_sequence"])
    assert [step["order"] for step in result["deployment_sequence"]] == list(range(1, 8))


def test_registry_durable_activation_precedes_session_activation_in_ordered_contract():
    result = compose_matrix_durability_readiness(
        session_preflight=_session_preflight(ready=True),
        registry_preflight=_registry_preflight(ready=True),
        session_status=_status(active=False),
        registry_status=_status(active=False),
    )

    actions = [step["action"] for step in result["deployment_sequence"]]
    assert actions.index("enable_registry_durable_mode") < actions.index("enable_session_durable_mode")
    session_step = next(step for step in result["deployment_sequence"] if step["action"] == "enable_session_durable_mode")
    registry_step = next(step for step in result["deployment_sequence"] if step["action"] == "enable_registry_durable_mode")
    assert registry_step["required"] is True
    assert session_step["required"] is True


def test_no_blockers_when_both_preflights_ready_even_if_activation_is_still_pending():
    result = compose_matrix_durability_readiness(
        session_preflight=_session_preflight(ready=True),
        registry_preflight=_registry_preflight(ready=True),
        session_status=_status(active=False),
        registry_status=_status(active=False),
    )

    assert result["scientific_trail_activation_ready"] is True
    assert result["scientific_trail_durable_active"] is False
    assert result["blockers"] == []
