import pytest

import oc_orchid_atlas


def test_exact_atlas_requires_server_side_database_credential(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError):
        oc_orchid_atlas.require_internal_database_access()


def test_exact_atlas_is_available_to_trusted_internal_operator(monkeypatch):
    database_url = "postgresql://trusted-internal-only/example"
    monkeypatch.setenv("DATABASE_URL", database_url)
    assert oc_orchid_atlas.require_internal_database_access() == database_url


def test_exact_atlas_output_is_explicitly_marked_restricted():
    assert "RESTRICTED_EXACT" in oc_orchid_atlas.RESTRICTED_ATLAS_OUTPUT
