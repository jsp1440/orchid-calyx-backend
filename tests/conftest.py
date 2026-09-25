import os
import re
import shutil

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
    config.addinivalue_line(
        "markers",
        "requires_postgres(*env_names, psql=False): needs a reachable PostgreSQL test "
        "database (TEST_DATABASE_URL, then DATABASE_URL, unless env names are given); "
        "skipped with the driver's reason when none is usable",
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
    for item in items:
        marker = item.get_closest_marker(REQUIRES_POSTGRES_MARKER)
        if marker is None:
            continue
        reason = _requires_postgres_skip_reason(marker)
        if reason:
            item.add_marker(pytest.mark.skip(reason=reason))


# ---------------------------------------------------------------------------
# PostgreSQL-backed tests
# ---------------------------------------------------------------------------
#
# Several suites need a real, disposable PostgreSQL (BUILD-087B provisions one
# in CI). Off-runner they must SKIP with the exact reason rather than error in
# fixture setup. A TCP probe is not enough: this sandbox, like many developer
# machines, has *something* listening on localhost:5432 that does not know the
# placeholder role, so only a real connection attempt is an honest gate.
#
#     pytestmark = pytest.mark.requires_postgres            # TEST_DATABASE_URL, then DATABASE_URL
#     pytestmark = pytest.mark.requires_postgres("DATABASE_URL", psql=True)
#
REQUIRES_POSTGRES_MARKER = "requires_postgres"
_DEFAULT_POSTGRES_ENV = ("TEST_DATABASE_URL", "DATABASE_URL")
_postgres_probe_cache: dict[str, str | None] = {}


def _redact_dsn(dsn: str) -> str:
    return re.sub(r"://([^:/@]+):[^@]*@", r"://\1:***@", dsn)


def postgres_unavailable_reason(dsn: str | None) -> str | None:
    """Return why ``dsn`` cannot be used for tests, or ``None`` when it can.

    The probe opens one real connection and runs ``SELECT 1``. The result is
    cached per DSN for the session so a suite of hundreds of gated tests costs
    one connection attempt.
    """
    if not dsn:
        return "PostgreSQL test database not configured (set TEST_DATABASE_URL or DATABASE_URL)"
    if dsn in _postgres_probe_cache:
        return _postgres_probe_cache[dsn]
    plain = re.sub(r"^postgres(ql)?\+\w+://", "postgresql://", dsn)
    reason: str | None
    try:
        import psycopg
    except ImportError:
        psycopg = None
    try:
        if psycopg is not None:
            with psycopg.connect(plain, connect_timeout=3) as conn:
                conn.execute("SELECT 1")
        else:
            from sqlalchemy import create_engine, text

            engine = create_engine(dsn, connect_args={"connect_timeout": 3})
            try:
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
            finally:
                engine.dispose()
        reason = None
    except Exception as exc:  # noqa: BLE001 - any driver failure is a precise skip reason
        detail = " ".join(str(exc).split())[:300]
        reason = f"PostgreSQL not usable at {_redact_dsn(dsn)}: {type(exc).__name__}: {detail}"
    _postgres_probe_cache[dsn] = reason
    return reason


def _requires_postgres_skip_reason(marker: pytest.Mark) -> str | None:
    env_names = tuple(str(name) for name in marker.args) or _DEFAULT_POSTGRES_ENV
    dsn = next(
        (os.environ.get(name) for name in env_names if os.environ.get(name)), None
    )
    reason = postgres_unavailable_reason(dsn)
    if reason:
        return reason
    if marker.kwargs.get("psql") and shutil.which("psql") is None:
        return "psql client binary not found on PATH"
    return None
