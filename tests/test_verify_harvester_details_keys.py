"""Guards the payload classifier used to verify HARVESTER-PRODUCTIVITY-001's
candidate key list against real recorded runs (#1008 follow-up).

``classify_payload`` must agree with ``read_counter`` about what a payload
carries -- it is built from that same function specifically so the diagnostic
can never report a key as "matched" that the production module would not
actually read, or vice versa.
"""

import importlib.util
import pathlib

_SPEC = importlib.util.spec_from_file_location(
    "verify_harvester_details_keys",
    pathlib.Path(__file__).resolve().parents[1] / "scripts" / "verify_harvester_details_keys.py",
)
verify = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(verify)


def test_a_non_mapping_payload_is_reported_as_such_not_as_zero_matches():
    result = verify.classify_payload("corrupt")
    assert result["is_mapping"] is False
    assert result["matched"] == {}
    assert result["unmatched_keys"] == []


def test_a_recognised_alias_is_matched_to_its_counter():
    result = verify.classify_payload({"rows_inserted": 5})
    assert result["matched"] == {"records_new": "rows_inserted"}
    assert result["unmatched_keys"] == []


def test_an_unrecognised_key_is_reported_unmatched_not_guessed():
    result = verify.classify_payload({"mystery_total": 99})
    assert result["matched"] == {}
    assert result["unmatched_keys"] == ["mystery_total"]


def test_a_key_present_but_unusable_is_not_counted_as_matched():
    # "records_inserted" is a candidate alias, but a negative value is
    # discarded by read_counter -- classify_payload must not credit the alias
    # for a value the production module would treat as unavailable.
    result = verify.classify_payload({"records_inserted": -3})
    assert result["matched"] == {}
    assert result["unmatched_keys"] == ["records_inserted"]


def test_mixed_matched_and_unmatched_keys_are_both_reported():
    result = verify.classify_payload({"rows_inserted": 5, "extra_field": "x"})
    assert result["matched"] == {"records_new": "rows_inserted"}
    assert result["unmatched_keys"] == ["extra_field"]


def test_summarise_job_reports_uninstrumented_when_nothing_matches():
    class FakeCursor:
        def execute(self, *_args, **_kwargs):
            pass

        def fetchall(self):
            return [{"details": {"mystery_total": 1}}, {"details": "corrupt"}]

    row = verify.summarise_job(FakeCursor(), "audit_traitbank_trait_coverage")
    assert row["instrumented"] is False
    assert row["non_mapping_payloads"] == 1
    assert row["unmatched_top_level_keys"] == {"mystery_total": 1}


def test_summarise_job_reports_instrumented_when_a_counter_matches():
    class FakeCursor:
        def execute(self, *_args, **_kwargs):
            pass

        def fetchall(self):
            return [{"details": {"rows_inserted": 3}}, {"details": {"rows_inserted": 0}}]

    row = verify.summarise_job(FakeCursor(), "audit_literature_extraction_coverage")
    assert row["instrumented"] is True
    assert row["matched_counter_aliases"] == {"records_new=rows_inserted": 2}


def test_main_fails_closed_without_database_url(monkeypatch):
    monkeypatch.setattr(verify, "DATABASE_URL", "")
    assert verify.main() == 1
