"""The hosted acceptance manifest is real, chained, and admissible."""

from __future__ import annotations

import hashlib
import importlib.util
import itertools
import os
import shutil
from pathlib import Path

import pytest

from app.calyx_orchestrator.traitbank_validation_executor import parse_targets

REPO_ROOT = Path(__file__).resolve().parents[1]
BRAIN = os.environ.get("OC_BRAIN_REPO_PATH", "").strip()

pytestmark = pytest.mark.skipif(
    not BRAIN
    or not (Path(BRAIN) / "calyx_brain" / "traitbank_validation.py").is_file(),
    reason="OC_BRAIN_REPO_PATH must name a Brain checkout with "
    "calyx_brain/traitbank_validation.py",
)


def _module():
    spec = importlib.util.spec_from_file_location(
        "oc_autonomy_acceptance_manifest",
        REPO_ROOT / "scripts" / "oc_autonomy_acceptance_manifest.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    for relative in (
        "data/traitbank/darwin_1862_batch.json",
        "app/traitbank/guards.py",
        "app/calyx_orchestrator/program_cycle.py",
    ):
        target = workspace / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / relative, target)
    (workspace / ".git").mkdir()
    (workspace / ".git" / "HEAD").write_text(
        "ref: refs/heads/autonomy/hosted-acceptance\n", encoding="ascii"
    )
    return workspace


def test_manifest_is_chained_pinned_and_admissible(tmp_path):
    workspace = _workspace(tmp_path)
    work = _module().build_manifest(workspace, Path(BRAIN))["work"]

    assert [item["work_id"] for item in work] == [
        "traitbank-darwin_1862_batch",
        "source-app-calyx_orchestrator-program_cycle",
        "source-app-traitbank-guards",
    ]
    assert work[0]["depends_on"] == []
    for previous, item in itertools.pairwise(work):
        assert item["depends_on"] == [previous["work_id"]]

    jobs = work[0]["packet"]["jobs"]
    assert [job["role_key"] for job in jobs] == [
        "repository_evidence_reader",
        "traitbank_batch_validator",
    ]
    files = jobs[1]["inputs"]["files"]
    # The same parser Calyx admission applies; sha256 pins the committed bytes.
    (target,) = parse_targets(files)
    assert (
        target.sha256
        == hashlib.sha256((workspace / target.path).read_bytes()).hexdigest()
    )
    for job in (j for item in work for j in item["packet"]["jobs"]):
        assert job["branch"] == "autonomy/hosted-acceptance"


def test_manifest_refuses_a_detached_workspace(tmp_path):
    workspace = _workspace(tmp_path)
    (workspace / ".git" / "HEAD").write_text("0" * 40 + "\n", encoding="ascii")
    with pytest.raises(SystemExit):
        _module().build_manifest(workspace, Path(BRAIN))
