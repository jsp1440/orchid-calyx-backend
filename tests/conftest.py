import os

import pytest

# Vendored harvesters.gbif_api raises at import when DATABASE_URL is unset, and
# state_helper builds a connection string from it. Offline tests never connect;
# a dummy URL keeps imports clean without any real database.
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")

# Marker for disposable, intentionally failing certification fixtures such as
# tests/calyx_certification/test_deterministic_failure_round2.py. They exist so
# the CALYX-AGENT-007 repair harness has a deterministic failure to repair, not
# to gate the repository suite, so the default collection deselects them. They
# stay selectable on purpose: pass ``-m calyx_certification_fixture`` (or a
# marker expression naming it), or name the test file on the command line.
CERTIFICATION_FIXTURE_MARKER = "calyx_certification_fixture"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        f"{CERTIFICATION_FIXTURE_MARKER}: disposable always-failing certification "
        "fixture; deselected by default, select with -m or by naming the file",
    )


def _explicitly_requested(config: pytest.Config, item: pytest.Item) -> bool:
    if CERTIFICATION_FIXTURE_MARKER in str(config.getoption("markexpr") or ""):
        return True
    item_path = item.path.resolve()
    for arg in config.invocation_params.args:
        candidate = str(arg).split("::", 1)[0]
        if not candidate or candidate.startswith("-"):
            continue
        try:
            requested = (config.invocation_params.dir / candidate).resolve()
        except OSError:
            continue
        if requested == item_path:
            return True
    return False


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    kept: list[pytest.Item] = []
    deselected: list[pytest.Item] = []
    for item in items:
        if item.get_closest_marker(
            CERTIFICATION_FIXTURE_MARKER
        ) and not _explicitly_requested(config, item):
            deselected.append(item)
        else:
            kept.append(item)
    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = kept
