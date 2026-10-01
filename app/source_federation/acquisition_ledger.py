"""Durable cache/lease service for shared external acquisitions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .acquisition import AcquisitionRecord, AcquisitionRequest
from .acquisition_models import AcquisitionLedgerRow


def _aware_utc(value: datetime | None) -> datetime | None:
    """Normalize DB datetimes for comparisons across SQLite/PostgreSQL."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class ClaimResult:
    action: str  # cache_hit | acquired_lease | in_flight | retry_blocked
    row_id: int
    resource_key: str


class AcquisitionLedger:
    def __init__(self, session: Session) -> None:
        self.session = session

    def claim(
        self,
        request: AcquisitionRequest,
        *,
        worker_id: str,
        lease_seconds: int = 120,
        now: datetime | None = None,
    ) -> ClaimResult:
        now = now or datetime.now(timezone.utc)
        row = (
            self.session.query(AcquisitionLedgerRow)
            .filter(AcquisitionLedgerRow.resource_key == request.key)
            .with_for_update()
            .first()
        )
        if row is None:
            row = AcquisitionLedgerRow(
                resource_key=request.key,
                provider=request.provider,
                canonical_url=request.canonical_url,
                status="leased",
                lease_holder=worker_id,
                lease_expires_at=now + timedelta(seconds=lease_seconds),
                consumers_json=json.dumps([request.consumer_module]),
            )
            self.session.add(row)
            try:
                self.session.commit()
            except IntegrityError:
                self.session.rollback()
                return self.claim(
                    request,
                    worker_id=worker_id,
                    lease_seconds=lease_seconds,
                    now=now,
                )
            return ClaimResult("acquired_lease", row.id, request.key)

        consumers = set(json.loads(row.consumers_json or "[]"))
        consumers.add(request.consumer_module)
        row.consumers_json = json.dumps(sorted(consumers))

        if row.status == "complete" and not request.force_refresh:
            self.session.commit()
            return ClaimResult("cache_hit", row.id, request.key)
        next_retry_at = _aware_utc(row.next_retry_at)
        if next_retry_at and next_retry_at > now:
            self.session.commit()
            return ClaimResult("retry_blocked", row.id, request.key)
        lease_expires_at = _aware_utc(row.lease_expires_at)
        if row.status == "leased" and lease_expires_at and lease_expires_at > now:
            self.session.commit()
            return ClaimResult("in_flight", row.id, request.key)

        row.status = "leased"
        row.lease_holder = worker_id
        row.lease_expires_at = now + timedelta(seconds=lease_seconds)
        self.session.commit()
        return ClaimResult("acquired_lease", row.id, request.key)

    def cached_payload(self, resource_key: str) -> str | None:
        row = (
            self.session.query(AcquisitionLedgerRow)
            .filter(AcquisitionLedgerRow.resource_key == resource_key)
            .first()
        )
        return row.payload_json if row and row.status == "complete" else None

    def complete(
        self,
        record: AcquisitionRecord,
        *,
        payload_json: str | None = None,
    ) -> None:
        row = (
            self.session.query(AcquisitionLedgerRow)
            .filter(AcquisitionLedgerRow.resource_key == record.key)
            .with_for_update()
            .one()
        )
        consumers = set(json.loads(row.consumers_json or "[]"))
        consumers.update(record.consumers)
        row.status = "complete"
        row.content_hash = record.content_hash
        row.durable_object_ref = record.durable_object_ref
        row.payload_json = payload_json
        row.etag = record.etag
        row.last_modified = record.last_modified
        row.provenance_json = json.dumps(dict(record.provenance), sort_keys=True)
        row.consumers_json = json.dumps(sorted(consumers))
        row.credits_spent += record.credits_spent
        row.retrieved_at = record.retrieved_at
        row.lease_holder = None
        row.lease_expires_at = None
        row.next_retry_at = None
        self.session.commit()

    def fail(
        self,
        resource_key: str,
        *,
        retry_after_seconds: int = 300,
        now: datetime | None = None,
    ) -> None:
        now = now or datetime.now(timezone.utc)
        row = (
            self.session.query(AcquisitionLedgerRow)
            .filter(AcquisitionLedgerRow.resource_key == resource_key)
            .with_for_update()
            .one()
        )
        row.status = "failed"
        row.failure_count += 1
        row.next_retry_at = now + timedelta(seconds=retry_after_seconds)
        row.lease_holder = None
        row.lease_expires_at = None
        self.session.commit()

    def metrics(self) -> dict[str, int]:
        rows = self.session.query(AcquisitionLedgerRow).all()
        return {
            "resources": len(rows),
            "completed": sum(r.status == "complete" for r in rows),
            "credits_spent": sum(r.credits_spent for r in rows),
            "failures": sum(r.failure_count for r in rows),
        }
