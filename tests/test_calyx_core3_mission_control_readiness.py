"""CALYX CORE 3 — Acceptance tests for the updated Mission Control readiness contract.

Issue #387: assemble_readiness_view now reflects licensed-image and
literature-pipeline readiness.
"""

from __future__ import annotations

from runtime.calyx_certification.mission_control_readiness import (
    assemble_readiness_view,
)


def _snapshot(*, certified: bool = True, blockers: list | None = None) -> dict:
    return {
        "certified": certified,
        "blockers": blockers or [],
        "snapshot_hash": "snap-abc",
    }


def _evidence(*, accepted: bool = True, blockers: list | None = None) -> dict:
    return {
        "evidence_accepted": accepted,
        "blockers": blockers or [],
        "artifact_hash": "ev-xyz",
    }


def _img_pipeline(*, ready: bool = True, blockers: list | None = None) -> dict:
    return {"ready": ready, "blockers": blockers or []}


def _lit_pipeline(*, ready: bool = True, blockers: list | None = None) -> dict:
    return {"ready": ready, "blockers": blockers or []}


# ---------------------------------------------------------------------------
# Backwards compatibility — existing call signature still works
# ---------------------------------------------------------------------------


class TestBackwardsCompat:
    def test_existing_call_returns_ready_when_all_green(self):
        result = assemble_readiness_view(_snapshot(), _evidence())
        assert result["status"] == "ready"
        assert result["production_action_authorized"] is False

    def test_existing_call_returns_blocked_with_blockers(self):
        result = assemble_readiness_view(
            _snapshot(certified=False, blockers=["snap_blocked"]),
            _evidence(accepted=False, blockers=["live_missing"]),
        )
        assert result["status"] == "blocked"
        assert "snap_blocked" in result["blockers"]
        assert "live_missing" in result["blockers"]

    def test_pipelines_key_is_present_with_null_status_when_omitted(self):
        result = assemble_readiness_view(_snapshot(), _evidence())
        assert "pipelines" in result
        assert result["pipelines"]["licensed_image"]["ready"] is None
        assert result["pipelines"]["literature"]["ready"] is None


# ---------------------------------------------------------------------------
# With pipeline reports included
# ---------------------------------------------------------------------------


class TestWithPipelines:
    def test_all_green_including_pipelines_is_ready(self):
        result = assemble_readiness_view(
            _snapshot(),
            _evidence(),
            licensed_image_pipeline=_img_pipeline(),
            literature_pipeline=_lit_pipeline(),
        )
        assert result["status"] == "ready"
        assert result["blockers"] == []
        assert result["pipelines"]["licensed_image"]["ready"] is True
        assert result["pipelines"]["literature"]["ready"] is True

    def test_image_pipeline_blocked_makes_overall_blocked(self):
        result = assemble_readiness_view(
            _snapshot(),
            _evidence(),
            licensed_image_pipeline=_img_pipeline(
                ready=False, blockers=["no_allowlisted_records"]
            ),
            literature_pipeline=_lit_pipeline(),
        )
        assert result["status"] == "blocked"
        assert "no_allowlisted_records" in result["blockers"]

    def test_literature_pipeline_blocked_makes_overall_blocked(self):
        result = assemble_readiness_view(
            _snapshot(),
            _evidence(),
            licensed_image_pipeline=_img_pipeline(),
            literature_pipeline=_lit_pipeline(
                ready=False, blockers=["doi_acquisition_incomplete"]
            ),
        )
        assert result["status"] == "blocked"
        assert "doi_acquisition_incomplete" in result["blockers"]

    def test_pipeline_blockers_merged_with_core_blockers(self):
        result = assemble_readiness_view(
            _snapshot(certified=False, blockers=["core_blocker"]),
            _evidence(),
            licensed_image_pipeline=_img_pipeline(
                ready=False, blockers=["image_blocker"]
            ),
            literature_pipeline=_lit_pipeline(
                ready=False, blockers=["lit_blocker"]
            ),
        )
        blockers = result["blockers"]
        assert "core_blocker" in blockers
        assert "image_blocker" in blockers
        assert "lit_blocker" in blockers

    def test_blockers_are_deduplicated_and_sorted(self):
        result = assemble_readiness_view(
            _snapshot(certified=False, blockers=["dup"]),
            _evidence(accepted=False, blockers=["dup"]),
            licensed_image_pipeline=_img_pipeline(ready=False, blockers=["dup"]),
        )
        assert result["blockers"].count("dup") == 1
        assert result["blockers"] == sorted(set(result["blockers"]))

    def test_only_image_pipeline_provided(self):
        result = assemble_readiness_view(
            _snapshot(),
            _evidence(),
            licensed_image_pipeline=_img_pipeline(ready=False, blockers=["x"]),
        )
        assert result["status"] == "blocked"
        assert result["pipelines"]["literature"]["ready"] is None

    def test_production_action_never_authorized(self):
        result = assemble_readiness_view(
            _snapshot(),
            _evidence(),
            licensed_image_pipeline=_img_pipeline(),
            literature_pipeline=_lit_pipeline(),
        )
        assert result["production_action_authorized"] is False
