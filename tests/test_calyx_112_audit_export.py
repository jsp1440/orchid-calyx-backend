from runtime.calyx_certification.audit_export import build_audit_export


def test_export_hash_is_deterministic():
    records = [{"lane": "L1", "certified": True}]
    first = build_audit_export(records)["export_hash"]
    second = build_audit_export(records)["export_hash"]
    assert first == second


def test_empty_export_fails_closed():
    assert build_audit_export([])["export_ready"] is False
