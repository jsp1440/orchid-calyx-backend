"""CALYX CORE 5 — Integration QA, deployment verification, and observability tests (closes #390).

Covers:
- build_calyx_core_certification returns valid structure.
- Route module checks report correct import state.
- Pipeline domain state reflects filesystem state.
- Reasoning ledger and publication safeguard checks.
- No production mutation flag is always true.
- Operator summary is a non-empty string.
- Certification is read-only and deterministic.
"""

from __future__ import annotations

from runtime.calyx_core_certification import (
    CONTRACT,
    build_calyx_core_certification,
)


class TestCertificationStructure:
    def test_contract_key_present(self, tmp_path):
        result = build_calyx_core_certification(
            taxonomy_root=tmp_path / "taxonomy",
            literature_root=tmp_path / "literature",
        )
        assert result["contract"] == CONTRACT

    def test_no_production_mutation(self, tmp_path):
        result = build_calyx_core_certification(
            taxonomy_root=tmp_path / "taxonomy",
            literature_root=tmp_path / "literature",
        )
        assert result["no_production_mutation"] is True

    def test_generated_at_present(self, tmp_path):
        result = build_calyx_core_certification(
            taxonomy_root=tmp_path / "taxonomy",
            literature_root=tmp_path / "literature",
        )
        assert result["generated_at"]

    def test_operator_summary_is_string(self, tmp_path):
        result = build_calyx_core_certification(
            taxonomy_root=tmp_path / "taxonomy",
            literature_root=tmp_path / "literature",
        )
        assert isinstance(result["operator_summary"], str)
        assert len(result["operator_summary"]) > 0

    def test_overall_status_present(self, tmp_path):
        result = build_calyx_core_certification(
            taxonomy_root=tmp_path / "taxonomy",
            literature_root=tmp_path / "literature",
        )
        assert result["overall_status"] in {"ready_for_validation", "import_errors_present"}


class TestRouteModuleChecks:
    def test_route_module_checks_present(self, tmp_path):
        result = build_calyx_core_certification(
            taxonomy_root=tmp_path / "taxonomy",
            literature_root=tmp_path / "literature",
        )
        checks = result["route_module_checks"]
        assert isinstance(checks, dict)
        assert "runtime.occurrence_staging" in checks
        assert "runtime.image_staging" in checks
        assert "runtime.literature_staging" in checks
        assert "runtime.graph_pipeline_readiness" in checks

    def test_core_modules_importable(self, tmp_path):
        result = build_calyx_core_certification(
            taxonomy_root=tmp_path / "taxonomy",
            literature_root=tmp_path / "literature",
        )
        checks = result["route_module_checks"]
        for module in ["runtime.occurrence_staging", "runtime.image_staging", "runtime.literature_staging"]:
            assert checks[module] == "importable", f"{module} reported: {checks[module]}"


class TestPipelineDomainState:
    def test_domains_all_present(self, tmp_path):
        result = build_calyx_core_certification(
            taxonomy_root=tmp_path / "taxonomy",
            literature_root=tmp_path / "literature",
        )
        domains = result["pipeline_domains"]
        assert "taxonomy" in domains
        assert "occurrences" in domains
        assert "licensed_images" in domains
        assert "literature" in domains

    def test_taxonomy_absent_when_dir_missing(self, tmp_path):
        result = build_calyx_core_certification(
            taxonomy_root=tmp_path / "no-such-dir",
            literature_root=tmp_path / "literature",
        )
        assert result["pipeline_domains"]["taxonomy"]["state"] == "intake_directory_absent"

    def test_taxonomy_present_when_dir_exists_empty(self, tmp_path):
        tax = tmp_path / "taxonomy"
        tax.mkdir()
        result = build_calyx_core_certification(
            taxonomy_root=tax,
            literature_root=tmp_path / "literature",
        )
        assert result["pipeline_domains"]["taxonomy"]["state"] == "no_releases"
        assert result["pipeline_domains"]["taxonomy"]["release_count"] == 0

    def test_taxonomy_counts_releases(self, tmp_path):
        import json

        tax = tmp_path / "taxonomy"
        release_dir = tax / "abc123"
        release_dir.mkdir(parents=True)
        (release_dir / "report.json").write_text(json.dumps({"release_id": "abc123"}))

        result = build_calyx_core_certification(
            taxonomy_root=tax,
            literature_root=tmp_path / "literature",
        )
        assert result["pipeline_domains"]["taxonomy"]["state"] == "inspected_releases_present"
        assert result["pipeline_domains"]["taxonomy"]["release_count"] == 1

    def test_occurrences_staging_ready(self, tmp_path):
        result = build_calyx_core_certification(
            taxonomy_root=tmp_path / "taxonomy",
            literature_root=tmp_path / "literature",
        )
        occ = result["pipeline_domains"]["occurrences"]
        assert occ["state"] == "staging_pipeline_ready"
        assert "gbif" in occ["supported_sources"]
        assert "inaturalist" in occ["supported_sources"]

    def test_licensed_images_staging_ready(self, tmp_path):
        result = build_calyx_core_certification(
            taxonomy_root=tmp_path / "taxonomy",
            literature_root=tmp_path / "literature",
        )
        img = result["pipeline_domains"]["licensed_images"]
        assert img["state"] == "staging_pipeline_ready"
        assert img["license_enforcement"] == "allowlist_active"


class TestReasoningLedgerAndPublication:
    def test_publication_automatic_false(self, tmp_path):
        result = build_calyx_core_certification(
            taxonomy_root=tmp_path / "taxonomy",
            literature_root=tmp_path / "literature",
        )
        pub = result["publication_safeguards"]
        assert pub["automatic_publication"] is False
        assert pub["production_mutation_without_owner_confirmation"] is False

    def test_ledger_automatic_publication_false(self, tmp_path):
        result = build_calyx_core_certification(
            taxonomy_root=tmp_path / "taxonomy",
            literature_root=tmp_path / "literature",
        )
        ledger = result["reasoning_ledger"]
        assert ledger["automatic_publication"] is False
        assert ledger["human_review_mandatory"] is True

    def test_publication_eligibility_blocked_by_default(self, tmp_path):
        result = build_calyx_core_certification(
            taxonomy_root=tmp_path / "taxonomy",
            literature_root=tmp_path / "literature",
        )
        ledger = result["reasoning_ledger"]
        assert ledger["publication_eligibility"] == "false_until_explicit_owner_approval"


class TestConfigurationPresence:
    def test_config_keys_all_reported(self, tmp_path):
        result = build_calyx_core_certification(
            taxonomy_root=tmp_path / "taxonomy",
            literature_root=tmp_path / "literature",
        )
        config = result["configuration_presence"]
        assert "DATABASE_URL" in config
        assert "CALYX_TAXONOMY_INTAKE_DIR" in config


class TestCertificationIdempotency:
    def test_two_calls_same_structure(self, tmp_path):
        kwargs = {"taxonomy_root": tmp_path / "taxonomy", "literature_root": tmp_path / "lit"}
        r1 = build_calyx_core_certification(**kwargs)
        r2 = build_calyx_core_certification(**kwargs)
        # Structure keys must match; timestamps may differ
        assert set(r1.keys()) == set(r2.keys())
        assert r1["contract"] == r2["contract"]
        assert r1["no_production_mutation"] == r2["no_production_mutation"]
