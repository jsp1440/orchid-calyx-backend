"""OC Critical Suites must cover every critical test file, by name.

``.github/workflows/oc-critical-suites.yml`` runs explicit lists of test files
on every pull request and push to main and oc-autonomous-integration. An
explicit list stops a suite from dropping out silently when it is renamed or
deleted (pytest exits 4), but not a NEW suite from never being added. This
test closes that side: every ``tests/test_*.py`` whose name marks it as a
security, auth, privacy, redaction, judging, ledger, fencing, lease or
locality suite must be listed, pending, or excluded here with a reason.

Names are matched on underscore-delimited tokens, so ``lease`` matches
``test_canonical_brain_leases`` and ``test_oc_swarm_lease_reconcile`` but not
the twenty-odd ``*release*`` suites (taxonomy/Hassler release lifecycle),
which are not lease tests.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "oc-critical-suites.yml"

CRITICAL_NAME = re.compile(
    r"(?:^|_)(?:security|auth|privacy|redact|judg|ledger|fenc|lease|locality"
    r"|coordinate|member_read|owner_only|blind)"
)

REQUIRED_LISTS = (
    "OC_CRITICAL_LEDGER_SUITES",
    "OC_CRITICAL_SECURITY_SUITES",
    "OC_CRITICAL_PRIVACY_SUITES",
)
PENDING_LIST = "OC_PENDING_CRITICAL_SUITES"

# Critical by name but deliberately not run by OC Critical Suites. Every entry
# needs a reason a reviewer can check.
EXCLUDED = {
    "tests/test_intelligence_ledger_postgres.py": (
        "email-intake intelligence ledger, not the acquisition ledger; every "
        "test skips unless INTELLIGENCE_LEDGER_DATABASE_URL names a migrated "
        "schema, so listing it would only add skips; its own workflow "
        "calyx-intelligence-ledger-validation.yml provisions that database"
    ),
}


def _is_critical_name(path: str) -> bool:
    name = Path(path).name
    return bool(CRITICAL_NAME.search(name[len("test_") : -len(".py")]))


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _paths(workflow: dict, key: str) -> list[str]:
    value = workflow["env"][key]
    return value.split()


def _required(workflow: dict) -> list[str]:
    return [path for key in REQUIRED_LISTS for path in _paths(workflow, key)]


def _test_files() -> list[str]:
    return sorted(
        f"tests/{path.name}" for path in (REPO_ROOT / "tests").glob("test_*.py")
    )


def _uncovered(files, required, pending, excluded) -> list[str]:
    covered = set(required) | set(pending) | set(excluded)
    return [path for path in files if _is_critical_name(path) and path not in covered]


def _job_runs(workflow: dict, job: str) -> str:
    return "\n".join(step.get("run", "") for step in workflow["jobs"][job]["steps"])


def test_required_suites_exist_and_are_listed_once() -> None:
    required = _required(_workflow())
    assert len(required) > 40
    duplicates = sorted({path for path in required if required.count(path) > 1})
    assert not duplicates, duplicates
    malformed = [p for p in required if not re.fullmatch(r"tests/test_\w+\.py", p)]
    assert not malformed, malformed
    missing = [path for path in required if not (REPO_ROOT / path).is_file()]
    assert not missing, f"listed critical suites that do not exist: {missing}"


def test_every_critical_named_test_file_is_covered() -> None:
    workflow = _workflow()
    files = _test_files()
    # Non-vacuous: 36 critical-named files existed when this guard was written.
    assert sum(_is_critical_name(path) for path in files) >= 30
    uncovered = _uncovered(
        files, _required(workflow), _paths(workflow, PENDING_LIST), EXCLUDED
    )
    assert not uncovered, (
        "critical-named test files missing from .github/workflows/"
        f"oc-critical-suites.yml (list them, or exclude them with a reason in "
        f"{Path(__file__).name}): {uncovered}"
    )


def test_pending_suites_are_not_also_required() -> None:
    workflow = _workflow()
    both = sorted(set(_paths(workflow, PENDING_LIST)) & set(_required(workflow)))
    assert not both, f"move these out of {PENDING_LIST}: {both}"


def test_exclusions_are_live_reasoned_and_not_listed() -> None:
    workflow = _workflow()
    listed = set(_required(workflow)) | set(_paths(workflow, PENDING_LIST))
    for path, reason in EXCLUDED.items():
        assert (REPO_ROOT / path).is_file(), f"stale exclusion: {path}"
        assert _is_critical_name(path), f"exclusion matches no critical name: {path}"
        assert path not in listed, f"excluded and listed: {path}"
        assert len(reason.split()) >= 5, f"exclusion needs a reason: {path}"


def test_both_jobs_run_every_list_with_complementary_postgres_selection() -> None:
    workflow = _workflow()
    suites = _job_runs(workflow, "critical-suites")
    postgres = _job_runs(workflow, "postgres-ledger")
    for key in (*REQUIRED_LISTS, PENDING_LIST):
        assert f'"${key}"' in suites, (key, "critical-suites")
        assert f'"${key}"' in postgres, (key, "postgres-ledger")
    assert '-m "not requires_postgres"' in suites
    assert "-m requires_postgres" in postgres
    assert "tests/test_critical_suite_coverage.py" in suites


def test_workflow_runs_on_main_and_integration_pushes_and_pull_requests() -> None:
    workflow = _workflow()
    triggers = workflow.get("on", workflow.get(True))
    for event in ("pull_request", "push"):
        assert set(triggers[event]["branches"]) >= {"main", "oc-autonomous-integration"}
    assert workflow["permissions"] == {"contents": "read"}


@pytest.mark.parametrize(
    ("name", "critical"),
    [
        ("tests/test_canonical_brain_leases.py", True),
        ("tests/test_oc_swarm_lease_reconcile.py", True),
        ("tests/test_acquisition_ledger_fencing.py", True),
        ("tests/test_show_day_judging_lock.py", True),
        ("tests/test_judge_auth_blind_judging.py", True),
        ("tests/test_no_precise_coordinates.py", True),
        ("tests/test_calyx_core_owner_only_show_management.py", True),
        ("tests/test_member_read_access.py", True),
        ("tests/test_security_fail_closed.py", True),
        ("tests/test_hassler_release_lifecycle.py", False),
        ("tests/test_release_identity.py", False),
        ("tests/test_taxonomy_preflight_release_gate.py", False),
    ],
)
def test_critical_name_rule(name: str, critical: bool) -> None:
    assert _is_critical_name(name) is critical


def test_uncovered_reports_a_file_dropped_from_every_list() -> None:
    files = ["tests/test_owner_authorization_gate.py", "tests/test_release_identity.py"]
    assert _uncovered(files, [], [], {}) == ["tests/test_owner_authorization_gate.py"]
    assert _uncovered(files, ["tests/test_owner_authorization_gate.py"], [], {}) == []
    assert _uncovered(files, [], ["tests/test_owner_authorization_gate.py"], {}) == []
