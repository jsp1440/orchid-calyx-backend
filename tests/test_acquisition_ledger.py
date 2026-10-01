from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.source_federation.acquisition import AcquisitionRecord, AcquisitionRequest
from app.source_federation.acquisition_models import AcquisitionLedgerRow
from app.source_federation.acquisition_ledger import AcquisitionLedger


def _ledger():
    engine = create_engine("sqlite:///:memory:")
    AcquisitionLedgerRow.__table__.create(engine)
    session = sessionmaker(bind=engine)()
    return AcquisitionLedger(session)


def _request(module="lexicon"):
    return AcquisitionRequest(
        url="https://example.org/taxon?id=7&utm_source=test",
        provider="powo",
        consumer_module=module,
    )


def test_duplicate_modules_coalesce_to_one_external_lease():
    ledger = _ledger()
    first = ledger.claim(_request("lexicon"), worker_id="w1")
    second = ledger.claim(_request("matrix"), worker_id="w2")
    assert first.action == "acquired_lease"
    assert second.action == "in_flight"


def test_completed_acquisition_becomes_zero_fetch_cache_hit():
    ledger = _ledger()
    request = _request()
    ledger.claim(request, worker_id="w1")
    record = AcquisitionRecord.completed(
        request=request,
        content=b"evidence",
        provenance={"source": "fixture"},
        credits_spent=1,
    )
    ledger.complete(record)
    hit = ledger.claim(_request("atlas"), worker_id="w2")
    assert hit.action == "cache_hit"
    assert ledger.metrics()["credits_spent"] == 1


def test_failure_blocks_immediate_credit_burning_retry():
    ledger = _ledger()
    now = datetime.now(timezone.utc)
    claim = ledger.claim(_request(), worker_id="w1", now=now)
    ledger.fail(claim.resource_key, retry_after_seconds=300, now=now)
    retry = ledger.claim(_request("brain"), worker_id="w2", now=now + timedelta(seconds=1))
    assert retry.action == "retry_blocked"


def test_expired_lease_can_be_recovered():
    ledger = _ledger()
    now = datetime.now(timezone.utc)
    ledger.claim(_request(), worker_id="dead-worker", lease_seconds=2, now=now)
    recovered = ledger.claim(
        _request("research_station"),
        worker_id="live-worker",
        now=now + timedelta(seconds=3),
    )
    assert recovered.action == "acquired_lease"
