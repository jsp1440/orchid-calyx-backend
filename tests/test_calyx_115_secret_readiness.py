from runtime.calyx_certification.secret_readiness import evaluate_secret_readiness


def test_accepts_configured_secret_metadata_without_values():
    result = evaluate_secret_readiness(
        [
            {
                "name": "CALYX_BACKEND_URL",
                "configured": True,
                "source": "github_actions",
            },
            {
                "name": "CALYX_OWNER_ACCESS_CODE",
                "configured": True,
                "source": "github_actions",
            },
        ]
    )
    assert result["ready"] is True
    assert result["secret_values_stored"] is False


def test_rejects_exposed_secret_value():
    result = evaluate_secret_readiness(
        [
            {
                "name": "CALYX_BACKEND_URL",
                "configured": True,
                "source": "github_actions",
                "value": "https://example.invalid",
            }
        ]
    )
    assert any(item.startswith("secret_value_exposed") for item in result["blockers"])
