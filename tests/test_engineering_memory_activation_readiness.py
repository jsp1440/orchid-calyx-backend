import pytest

from scripts.validate_engineering_memory_activation import (
    UnsafeValidationTarget,
    validated_ephemeral_url,
)

SAFE_URL = (
    "postgresql+psycopg://synthetic:synthetic@127.0.0.1:5432/"
    "engineering_memory_ephemeral_validation"
)


def test_activation_validator_accepts_only_explicit_loopback_ephemeral_target():
    assert (
        validated_ephemeral_url(
            {
                "ENGINEERING_MEMORY_EPHEMERAL_VALIDATION": "1",
                "ENGINEERING_MEMORY_TEST_DATABASE_URL": SAFE_URL,
            }
        )
        == SAFE_URL
    )


@pytest.mark.parametrize(
    "environment",
    [
        {"ENGINEERING_MEMORY_TEST_DATABASE_URL": SAFE_URL},
        {
            "ENGINEERING_MEMORY_EPHEMERAL_VALIDATION": "1",
            "ENGINEERING_MEMORY_TEST_DATABASE_URL": (
                "postgresql://user:password@production.example/db"
            ),
        },
        {
            "ENGINEERING_MEMORY_EPHEMERAL_VALIDATION": "1",
            "ENGINEERING_MEMORY_TEST_DATABASE_URL": (
                "postgresql://user:password@127.0.0.1/production"
            ),
        },
        {
            "ENGINEERING_MEMORY_EPHEMERAL_VALIDATION": "1",
            "ENGINEERING_MEMORY_TEST_DATABASE_URL": "sqlite:///ephemeral.db",
        },
    ],
)
def test_activation_validator_fails_closed(environment):
    with pytest.raises(UnsafeValidationTarget):
        validated_ephemeral_url(environment)
