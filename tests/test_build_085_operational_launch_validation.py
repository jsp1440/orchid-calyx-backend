import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "build_085_operational_launch_validation.py"


spec = importlib.util.spec_from_file_location("build_085", SCRIPT_PATH)
build_085 = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = build_085
spec.loader.exec_module(build_085)


def test_required_migrations_are_additive():
    for build_id, _, filename in build_085.MIGRATIONS:
        if build_id in {"BUILD-070", "BUILD-076A", "BUILD-079", "BUILD-081"}:
            continue
        assert build_085._is_additive_sql(filename)


def test_safety_checks_are_declared_and_passing_in_codebase():
    checks = build_085._safety_checks()
    assert checks
    assert all(check.passed for check in checks)


def test_fixture_proves_cancellation_and_resume_behavior():
    proof = build_085._fixture_cancel_resume_proof()
    assert proof["proof"]["cancellation_leaves_checkpoint"] is True
    assert proof["proof"]["resume_continues_pending_only"] is True
    assert proof["proof"]["completed_items_not_reimported"] is True


def test_final_report_returns_not_ready_with_exact_blocker_when_env_missing():
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "final-report"],
        check=True,
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        env={"PYTHONPATH": str(ROOT)},
    )
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "NOT READY"
    assert payload["blocker"] == "DATABASE_URL is not configured"
