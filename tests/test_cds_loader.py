from runtime.cds_loader import CDSRegistryLoader


def test_cds_loader_summary_reports_modules():
    summary = CDSRegistryLoader().summary()
    assert summary["build"] == "BUILD-012B"
    assert summary["module_count"] >= 1


def test_cds_loader_finds_database_inspector():
    module = CDSRegistryLoader().module("DatabaseInspector")
    assert module["module_id"] == "CDS-ENG-002"
    assert module["status"] == "live-ready"
