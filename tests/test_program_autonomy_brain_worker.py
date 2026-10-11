"""The deployable Brain-pulse worker entrypoint fails closed on configuration."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from runtime.program_autonomy_brain_worker import build_worker, configuration_problems

REPO_ROOT = Path(__file__).resolve().parents[1]
BRAIN = os.environ.get("OC_BRAIN_REPO_PATH", "").strip()


def test_every_missing_setting_is_named():
    assert configuration_problems({}) == [
        "OC_BRAIN_CHECKOUT_UNSET",
        "OC_BRAIN_WORK_MANIFEST_UNSET",
        "OC_BRAIN_PULSE_LEDGER_UNSET",
        "CALYX_BACKEND_BASE_URL_UNSET",
        "CALYX_API_KEY_UNSET",
    ]


def test_wrong_paths_are_rejected_before_any_loop(tmp_path):
    env = {
        "OC_BRAIN_CHECKOUT": str(tmp_path),
        "OC_BRAIN_WORK_MANIFEST": str(tmp_path / "missing.json"),
        "OC_BRAIN_PULSE_LEDGER": str(tmp_path / "ledger.json"),
        "CALYX_BACKEND_BASE_URL": "http://127.0.0.1:9",
        "CALYX_API_KEY": "fixture",
    }
    assert configuration_problems(env) == [
        "OC_BRAIN_CHECKOUT_MISSING_AUTONOMY_PULSE",
        "OC_BRAIN_WORK_MANIFEST_NOT_FOUND",
    ]
    with pytest.raises(ValueError, match="OC_BRAIN_CHECKOUT_MISSING_AUTONOMY_PULSE"):
        build_worker(env)


def test_unconfigured_entrypoint_reports_configuration_unavailable_and_exits():
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("OC_BRAIN_", "CALYX_"))
    }
    env["PYTHONPATH"] = str(REPO_ROOT)
    completed = subprocess.run(
        [sys.executable, "-m", "runtime.program_autonomy_brain_worker"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    record = json.loads(completed.stdout.strip().splitlines()[-1])
    assert record["started"] is False
    assert record["zero_reason"] == "configuration_unavailable"
    assert "CALYX_API_KEY_UNSET" in record["detail"]


@pytest.mark.skipif(
    not BRAIN or not (Path(BRAIN) / "calyx_brain" / "autonomy_pulse.py").is_file(),
    reason="OC_BRAIN_REPO_PATH must name a Brain checkout with autonomy_pulse.py",
)
def test_disabled_policy_never_builds_a_worker(tmp_path):
    manifest = tmp_path / "work.json"
    manifest.write_text(json.dumps({"work": []}))
    env = {
        "OC_BRAIN_CHECKOUT": BRAIN,
        "OC_BRAIN_WORK_MANIFEST": str(manifest),
        "OC_BRAIN_PULSE_LEDGER": str(tmp_path / "ledger.json"),
        "CALYX_BACKEND_BASE_URL": "http://127.0.0.1:9",
        "CALYX_API_KEY": "fixture",
        "CALYX_PROGRAM_AUTONOMY_ENABLED": "false",
    }
    with pytest.raises(PermissionError, match="PROGRAM_AUTONOMY_NOT_AUTHORIZED"):
        build_worker(env)
    with pytest.raises(ValueError, match="BACKOFF_OUT_OF_RANGE"):
        build_worker(
            {
                **env,
                "CALYX_PROGRAM_AUTONOMY_ENABLED": "true",
                "CALYX_PROGRAM_AUTONOMY_OWNER": "backend_api_key",
                "OC_BRAIN_PULSE_BACKOFF_BASE_SECONDS": "0",
            }
        )
