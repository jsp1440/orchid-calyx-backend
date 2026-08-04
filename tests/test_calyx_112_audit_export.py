from runtime.calyx_certification.audit_export import build_audit_export


def test_export_hash_is_deterministic():
    records = [{"lane": "L1", "certified": True}]
    assert build_audit_export(records)["export_hash"] == build_audit_export(records)["export_hash"]


def test_empty_export_fails_closed():
    assert build_audit_export([])["export_ready"] is False
