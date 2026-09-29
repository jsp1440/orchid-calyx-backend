"""The runtime reads the Brain at the ref the Brain serves.

Until 2026-09-25 DEFAULT_BRAIN_REF was ``calyx-core-operational-foundation``, a
frozen ancestor of ``main`` (54692d7, 2026-07-03) on which
config/infrastructure_registry.json is 1.1 where main serves 1.2. The default
is now ``main``. The live test is opt-in (CALYX_BRAIN_LIVE_TEST=1) because it
needs the network; the deterministic tests need nothing.
"""

from __future__ import annotations

import os

import pytest

from runtime.config_loader import (
    BRAIN_SERVED_REF,
    DEFAULT_BRAIN_REF,
    BrainConfigLoader,
    BrainConfigSource,
    LastKnownStore,
)

FIVE_RECORDS = (
    "config/calyx_core_manifest.json",
    "config/runtime_services.json",
    "config/infrastructure_registry.json",
    "config/governance_policy.json",
    "config/knowledge_preservation_policy.json",
)


def test_the_default_ref_is_the_served_ref():
    assert DEFAULT_BRAIN_REF == BRAIN_SERVED_REF == "main"


def test_a_source_built_from_a_clean_environment_is_not_stale(monkeypatch):
    monkeypatch.delenv("CALYX_BRAIN_REF", raising=False)
    source = BrainConfigSource.from_env()
    assert source.ref == "main"
    assert source.stale is False
    assert source.describe()["resolution"] == "not_attempted"


def test_an_explicit_pin_still_wins_and_is_reported_stale(monkeypatch):
    monkeypatch.setenv("CALYX_BRAIN_REF", "calyx-core-operational-foundation")
    source = BrainConfigSource.from_env()
    assert source.ref == "calyx-core-operational-foundation"
    assert source.stale is True
    assert source.describe()["ref_commit"].startswith("54692d7")


@pytest.mark.skipif(
    os.getenv("CALYX_BRAIN_LIVE_TEST") != "1",
    reason="live GitHub read; set CALYX_BRAIN_LIVE_TEST=1 to run",
)
@pytest.mark.parametrize("ref", ["main", "calyx-core-operational-foundation"])
def test_live_both_refs_serve_all_five_records(ref):
    loader = BrainConfigLoader(BrainConfigSource(ref=ref), last_known=LastKnownStore())
    for path in FIVE_RECORDS:
        result = loader.load_with_source(path)
        assert result.available, (ref, path, result.config_source.get("error"))
        assert result.config_source["status"] == "loaded"
