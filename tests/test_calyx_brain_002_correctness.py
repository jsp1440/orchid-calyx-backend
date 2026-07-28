"""Regression tests for CALYX-BRAIN-002 correctness blockers.

Covers the five defects identified in the PR review:

1. Publication approval is now version-bound.
2. Append/review/publish are atomic (no lost-update under concurrent access).
3. Unresolved conflicts can be superseded via an explicit mechanism.
4. Creation uses deterministic_ledger_id() and is idempotent.
5. Entry sequence values are service-assigned and strictly monotonic.
"""

from __future__ import annotations

import hashlib
import json
import threading
from uuid import uuid4

import pytest

from app.reasoning_ledger.identity import deterministic_ledger_id
from app.reasoning_ledger.models import (
    ConflictState,
    LedgerEntry,
    LedgerEntryKind,
    LedgerPublicationError,
    LedgerStatus,
    LedgerValidationError,
    ReasoningLedger,
    ReviewDecision,
    ReviewOutcome,
    UncertaintyMarker,
)
from app.reasoning_ledger.service import (
    InMemoryReasoningLedgerService,
    LedgerTenantError,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

TENANT = "tenant-alpha"
PROJECT = "proj-001"
OTHER_TENANT = "tenant-beta"
OTHER_PROJECT = "proj-002"


def _svc() -> InMemoryReasoningLedgerService:
    return InMemoryReasoningLedgerService()


def _create(svc: InMemoryReasoningLedgerService, **kwargs) -> ReasoningLedger:
    defaults: dict[str, str] = {
        "tenant_id": TENANT,
        "project_id": PROJECT,
        "title": "Test ledger",
        "description": "",
        "created_by": "researcher-1",
    }
    defaults.update(kwargs)
    return svc.create(**defaults)


def _make_entry(
    *,
    kind: LedgerEntryKind = LedgerEntryKind.SUPPORT,
    text: str = "evidence text",
    confidence: float | None = 0.9,
    conflict_state: ConflictState = ConflictState.UNRESOLVED,
    tenant_id: str = TENANT,
    project_id: str = PROJECT,
) -> LedgerEntry:
    uncertainty = (
        UncertaintyMarker(confidence=confidence) if confidence is not None else None
    )
    return LedgerEntry(
        kind=kind,
        text=text,
        author="researcher-1",
        tenant_id=tenant_id,
        project_id=project_id,
        uncertainty=uncertainty,
        conflict_state=conflict_state,
    )


def _make_conclusion(confidence: float = 0.8) -> LedgerEntry:
    return _make_entry(
        kind=LedgerEntryKind.CONCLUSION, text="conclusion", confidence=confidence
    )


def _make_conflict(text: str = "conflict") -> LedgerEntry:
    return _make_entry(kind=LedgerEntryKind.CONFLICT, text=text, confidence=None)


def _approve_decision(ledger_version: int = 1) -> ReviewDecision:
    return ReviewDecision(
        reviewer="reviewer-1",
        outcome=ReviewOutcome.APPROVED,
        rationale="looks good",
        ledger_version=ledger_version,
    )


def _build_publishable_ledger(svc: InMemoryReasoningLedgerService) -> ReasoningLedger:
    """Create and advance a ledger to a publishable state."""
    ledger = _create(svc)
    ledger = svc.append(
        str(ledger.ledger_id), _make_conclusion(0.9), actor="r1", tenant_id=TENANT
    )
    ledger = svc.review(str(ledger.ledger_id), _approve_decision(), tenant_id=TENANT)
    return ledger


# ===========================================================================
# Fix 1: Version-bound approval
# ===========================================================================


class TestVersionBoundApproval:
    """Approval must be tied to the exact ledger version it was granted for."""

    def test_approval_applies_to_exact_version(self):
        svc = _svc()
        ledger = _create(svc)
        ledger = svc.append(
            str(ledger.ledger_id), _make_conclusion(), actor="r1", tenant_id=TENANT
        )
        decision = _approve_decision()
        ledger = svc.review(str(ledger.ledger_id), decision, tenant_id=TENANT)

        assert ledger.status is LedgerStatus.APPROVED
        assert ledger.has_human_approval

        # The bound decision must reference the current version.
        bound = ledger.review_decisions[-1]
        assert bound.ledger_version == ledger.version

    def test_approval_invalidated_after_append(self):
        svc = _svc()
        ledger = _create(svc)
        ledger = svc.append(
            str(ledger.ledger_id), _make_conclusion(), actor="r1", tenant_id=TENANT
        )
        ledger = svc.review(
            str(ledger.ledger_id), _approve_decision(), tenant_id=TENANT
        )
        assert ledger.has_human_approval, "should be approved at this point"

        # Append a new entry — prior approval must be invalidated.
        ledger = svc.append(
            str(ledger.ledger_id), _make_entry(), actor="r1", tenant_id=TENANT
        )

        assert not ledger.has_human_approval, (
            "approval must not survive a subsequent append"
        )
        assert ledger.status is LedgerStatus.UNDER_REVIEW

    def test_publication_blocked_after_post_approval_append(self):
        svc = _svc()
        ledger = _build_publishable_ledger(svc)

        # Append another entry — should invalidate approval.
        ledger = svc.append(
            str(ledger.ledger_id), _make_entry(), actor="r1", tenant_id=TENANT
        )

        violations = svc.validate(str(ledger.ledger_id), tenant_id=TENANT)
        assert any("approval" in v.lower() for v in violations), (
            f"expected approval violation, got: {violations}"
        )

    def test_re_approval_after_append_restores_publishability(self):
        svc = _svc()
        ledger = _build_publishable_ledger(svc)

        # Append invalidates approval.
        ledger = svc.append(
            str(ledger.ledger_id), _make_entry(), actor="r1", tenant_id=TENANT
        )
        assert not ledger.has_human_approval

        # Re-review with APPROVED outcome at the new version.
        ledger = svc.review(
            str(ledger.ledger_id), _approve_decision(), tenant_id=TENANT
        )
        assert ledger.has_human_approval
        assert ledger.status is LedgerStatus.APPROVED

    def test_stale_approval_version_does_not_satisfy_gate(self):
        """An old approval with a lower ledger_version must not satisfy has_human_approval."""
        svc = _svc()
        ledger = _create(svc)
        ledger = svc.append(
            str(ledger.ledger_id), _make_conclusion(), actor="r1", tenant_id=TENANT
        )
        ledger = svc.review(
            str(ledger.ledger_id), _approve_decision(), tenant_id=TENANT
        )

        # Record the version at which approval was granted.
        approval_version = ledger.review_decisions[-1].ledger_version

        # Append increments version, triggering a status reset.
        ledger = svc.append(
            str(ledger.ledger_id), _make_entry(), actor="r1", tenant_id=TENANT
        )
        assert ledger.version > approval_version
        assert not ledger.has_human_approval


# ===========================================================================
# Fix 2: Atomic operations
# ===========================================================================


class TestAtomicOperations:
    """Concurrent append/review/publish must not produce lost updates."""

    def test_concurrent_appends_produce_sequential_versions(self):
        svc = _svc()
        ledger = _create(svc)
        lid = str(ledger.ledger_id)
        n_threads = 20
        errors: list[Exception] = []

        def append_entry(i: int) -> None:
            try:
                svc.append(
                    lid,
                    _make_entry(text=f"entry {i}"),
                    actor="r1",
                    tenant_id=TENANT,
                )
            except (LedgerValidationError, LedgerTenantError) as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=append_entry, args=(i,)) for i in range(n_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"unexpected errors during concurrent appends: {errors}"
        final = svc.current(lid, tenant_id=TENANT)
        assert len(final.entries) == n_threads, (
            f"expected {n_threads} entries, got {len(final.entries)}"
        )
        # Versions must be consecutive and unique.
        all_versions = [v.version for v in svc.history(lid, tenant_id=TENANT)]
        assert sorted(all_versions) == list(range(1, len(all_versions) + 1))

    def test_concurrent_appends_unique_sequences(self):
        svc = _svc()
        ledger = _create(svc)
        lid = str(ledger.ledger_id)
        n_threads = 10

        def append_entry(i: int) -> None:
            svc.append(
                lid,
                _make_entry(text=f"entry {i}"),
                actor="r1",
                tenant_id=TENANT,
            )

        threads = [
            threading.Thread(target=append_entry, args=(i,)) for i in range(n_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        final = svc.current(lid, tenant_id=TENANT)
        sequences = [e.sequence for e in final.entries]
        assert sequences == sorted(sequences), (
            "sequences must be monotonically increasing"
        )
        assert len(set(sequences)) == len(sequences), "sequences must be unique"

    def test_review_and_append_no_lost_update(self):
        """A review that completes concurrently with an append must not be lost
        from the history; the history must contain all operations."""
        svc = _svc()
        ledger = _create(svc)
        lid = str(ledger.ledger_id)
        svc.append(lid, _make_conclusion(), actor="r1", tenant_id=TENANT)

        barrier = threading.Barrier(2)
        results: list[int] = []

        def do_review() -> None:
            barrier.wait()
            svc.review(lid, _approve_decision(), tenant_id=TENANT)
            results.append(1)

        def do_append() -> None:
            barrier.wait()
            svc.append(lid, _make_entry(), actor="r1", tenant_id=TENANT)
            results.append(2)

        t1 = threading.Thread(target=do_review)
        t2 = threading.Thread(target=do_append)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Both operations must have completed without raising.
        assert len(results) == 2
        history = svc.history(lid, tenant_id=TENANT)
        assert len(history) >= 3  # initial + append + (review or append)


# ===========================================================================
# Fix 3: Conflict supersession
# ===========================================================================


class TestConflictSupersession:
    """Unresolved conflicts must be explicitly resolvable; the gate evaluates
    the effective state of each conflict, not its original frozen state."""

    def test_unresolved_conflict_blocks_publication(self):
        svc = _svc()
        ledger = _create(svc)
        lid = str(ledger.ledger_id)
        svc.append(lid, _make_conflict(), actor="r1", tenant_id=TENANT)
        svc.append(lid, _make_conclusion(), actor="r1", tenant_id=TENANT)
        svc.review(lid, _approve_decision(), tenant_id=TENANT)

        violations = svc.validate(lid, tenant_id=TENANT)
        assert any("conflict" in v.lower() for v in violations)

    def test_resolved_conflict_no_longer_blocks_publication(self):
        svc = _svc()
        ledger = _create(svc)
        lid = str(ledger.ledger_id)

        conflict_entry = _make_conflict()
        ledger = svc.append(lid, conflict_entry, actor="r1", tenant_id=TENANT)
        conflict_id = ledger.entries[-1].entry_id  # service-assigned entry

        svc.append(lid, _make_conclusion(), actor="r1", tenant_id=TENANT)

        # Resolve the conflict before review.
        ledger = svc.resolve_conflict(lid, conflict_id, tenant_id=TENANT)
        assert conflict_id in ledger.resolved_conflict_ids
        assert not ledger.unresolved_conflicts

        # Review and check gate.
        ledger = svc.review(lid, _approve_decision(), tenant_id=TENANT)
        violations = svc.validate(lid, tenant_id=TENANT)
        assert not any("conflict" in v.lower() for v in violations), (
            f"resolved conflict still blocks publication: {violations}"
        )

    def test_resolve_conflict_is_append_only(self):
        """The original CONFLICT entry must remain in the entries list."""
        svc = _svc()
        ledger = _create(svc)
        lid = str(ledger.ledger_id)

        conflict_entry = _make_conflict()
        ledger = svc.append(lid, conflict_entry, actor="r1", tenant_id=TENANT)
        conflict_id = ledger.entries[-1].entry_id

        ledger = svc.resolve_conflict(lid, conflict_id, tenant_id=TENANT)

        # The original entry must still be present.
        entry_ids = {e.entry_id for e in ledger.entries}
        assert conflict_id in entry_ids, "original conflict entry must remain"
        # …and the conflict_state on the original entry is unchanged.
        original = next(e for e in ledger.entries if e.entry_id == conflict_id)
        assert original.conflict_state is ConflictState.UNRESOLVED
        # …but the ledger considers it resolved via resolved_conflict_ids.
        assert conflict_id in ledger.resolved_conflict_ids

    def test_resolve_nonexistent_conflict_raises(self):
        svc = _svc()
        ledger = _create(svc)
        lid = str(ledger.ledger_id)
        with pytest.raises(LedgerValidationError, match="not a CONFLICT entry"):
            svc.resolve_conflict(lid, uuid4(), tenant_id=TENANT)

    def test_resolve_already_resolved_conflict_raises(self):
        svc = _svc()
        ledger = _create(svc)
        lid = str(ledger.ledger_id)
        ledger = svc.append(lid, _make_conflict(), actor="r1", tenant_id=TENANT)
        conflict_id = ledger.entries[-1].entry_id
        svc.resolve_conflict(lid, conflict_id, tenant_id=TENANT)
        with pytest.raises(LedgerValidationError, match="already resolved"):
            svc.resolve_conflict(lid, conflict_id, tenant_id=TENANT)

    def test_resolve_conflict_cross_tenant_denied(self):
        svc = _svc()
        ledger = _create(svc)
        lid = str(ledger.ledger_id)
        ledger = svc.append(lid, _make_conflict(), actor="r1", tenant_id=TENANT)
        conflict_id = ledger.entries[-1].entry_id
        with pytest.raises(LedgerTenantError):
            svc.resolve_conflict(lid, conflict_id, tenant_id=OTHER_TENANT)

    def test_resolve_conflict_recorded_in_history(self):
        svc = _svc()
        ledger = _create(svc)
        lid = str(ledger.ledger_id)
        ledger = svc.append(lid, _make_conflict(), actor="r1", tenant_id=TENANT)
        conflict_id = ledger.entries[-1].entry_id
        pre_version = ledger.version

        svc.resolve_conflict(lid, conflict_id, tenant_id=TENANT)
        history = svc.history(lid, tenant_id=TENANT)

        # Resolution must produce a new version.
        assert history[-1].version == pre_version + 1
        assert conflict_id in history[-1].resolved_conflict_ids


# ===========================================================================
# Fix 4: Deterministic ledger identity
# ===========================================================================


class TestDeterministicLedgerIdentity:
    """create() must use deterministic_ledger_id(); repeated identical calls
    must be idempotent."""

    def test_create_uses_deterministic_id(self):
        svc = _svc()
        ledger = _create(svc)
        expected_id = deterministic_ledger_id(TENANT, PROJECT, "Test ledger")
        assert ledger.ledger_id == expected_id

    def test_identical_creation_is_idempotent(self):
        svc = _svc()
        l1 = _create(svc)
        l2 = _create(svc)
        assert l1.ledger_id == l2.ledger_id, "second create must return existing ledger"

    def test_same_title_different_tenant_produces_different_id(self):
        svc = _svc()
        l1 = _create(svc, tenant_id="tenant-a")
        l2 = _create(svc, tenant_id="tenant-b")
        assert l1.ledger_id != l2.ledger_id

    def test_same_title_different_project_produces_different_id(self):
        svc = _svc()
        l1 = _create(svc, project_id="proj-x")
        l2 = _create(svc, project_id="proj-y")
        assert l1.ledger_id != l2.ledger_id

    def test_idempotent_create_does_not_reset_history(self):
        """Idempotent creation must not clobber existing ledger history."""
        svc = _svc()
        ledger = _create(svc)
        lid = str(ledger.ledger_id)
        svc.append(lid, _make_entry(), actor="r1", tenant_id=TENANT)

        # Second create call must return the current (already-appended) ledger.
        l2 = _create(svc)
        assert l2.version == 2  # original + one append
        assert len(l2.entries) == 1

    def test_deterministic_id_is_stable_across_instances(self):
        """deterministic_ledger_id must be independent of service state."""
        id1 = deterministic_ledger_id(TENANT, PROJECT, "Stability test")
        id2 = deterministic_ledger_id(TENANT, PROJECT, "Stability test")
        assert id1 == id2


# ===========================================================================
# Fix 5: Strictly monotonic entry sequences
# ===========================================================================


class TestEntrySequences:
    """The service must assign strictly monotonic, zero-based sequence values
    regardless of the value the caller provides in the LedgerEntry."""

    def test_first_entry_gets_sequence_zero(self):
        svc = _svc()
        ledger = _create(svc)
        # Supply an arbitrary sequence value; it must be ignored.
        entry = LedgerEntry(
            kind=LedgerEntryKind.SUPPORT,
            text="entry text",
            author="r1",
            tenant_id=TENANT,
            project_id=PROJECT,
            sequence=999,
        )
        ledger = svc.append(str(ledger.ledger_id), entry, actor="r1", tenant_id=TENANT)
        assert ledger.entries[0].sequence == 0

    def test_subsequent_entries_get_strictly_increasing_sequences(self):
        svc = _svc()
        ledger = _create(svc)
        lid = str(ledger.ledger_id)
        for i in range(5):
            svc.append(
                lid, _make_entry(text=f"entry {i}"), actor="r1", tenant_id=TENANT
            )

        final = svc.current(lid, tenant_id=TENANT)
        sequences = [e.sequence for e in final.entries]
        assert sequences == list(range(5)), f"expected [0,1,2,3,4], got {sequences}"

    def test_caller_supplied_sequence_is_overridden(self):
        """The caller cannot dictate sequence; service always assigns it."""
        svc = _svc()
        ledger = _create(svc)
        lid = str(ledger.ledger_id)

        # Append two entries with caller-supplied sequence=0 both times.
        for _ in range(2):
            entry = LedgerEntry(
                kind=LedgerEntryKind.SUPPORT,
                text="same sequence attempt",
                author="r1",
                tenant_id=TENANT,
                project_id=PROJECT,
                sequence=0,
            )
            svc.append(lid, entry, actor="r1", tenant_id=TENANT)

        final = svc.current(lid, tenant_id=TENANT)
        assert final.entries[0].sequence == 0
        assert final.entries[1].sequence == 1

    def test_entry_fingerprint_reflects_assigned_sequence(self):
        """The fingerprint must be recomputed from the service-assigned sequence."""
        svc = _svc()
        ledger = _create(svc)
        lid = str(ledger.ledger_id)

        original_entry = _make_entry(text="deterministic entry")
        ledger = svc.append(lid, original_entry, actor="r1", tenant_id=TENANT)
        stored_entry = ledger.entries[-1]

        # The fingerprint must match recomputation from the assigned sequence.
        payload = {
            "entry_id": str(stored_entry.entry_id),
            "kind": stored_entry.kind.value,
            "version": stored_entry.version,
            "sequence": stored_entry.sequence,
            "text": stored_entry.text,
            "author": stored_entry.author,
            "tenant_id": stored_entry.tenant_id,
            "project_id": stored_entry.project_id,
        }
        expected_fp = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        assert stored_entry.fingerprint == expected_fp

    def test_sequence_continuity_after_concurrent_appends(self):
        """Sequences must form a contiguous range 0..n-1 even under concurrency."""
        svc = _svc()
        ledger = _create(svc)
        lid = str(ledger.ledger_id)
        n = 15

        def append_one(i: int) -> None:
            svc.append(
                lid, _make_entry(text=f"concurrent {i}"), actor="r1", tenant_id=TENANT
            )

        threads = [threading.Thread(target=append_one, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        final = svc.current(lid, tenant_id=TENANT)
        sequences = sorted(e.sequence for e in final.entries)
        assert sequences == list(range(n)), f"sequence gap detected: {sequences}"


# ===========================================================================
# Isolation and publication gate integration
# ===========================================================================


class TestPublicationGateIntegration:
    """End-to-end: ledger must only be publishable when all gate conditions hold."""

    def test_full_e2e_publish_path(self):
        svc = _svc()
        ledger = _build_publishable_ledger(svc)
        lid = str(ledger.ledger_id)

        violations = svc.validate(lid, tenant_id=TENANT)
        assert not violations, f"unexpected violations: {violations}"

        published = svc.publish(lid, tenant_id=TENANT)
        assert published.status is LedgerStatus.PUBLISHED

    def test_cross_tenant_read_denied(self):
        svc = _svc()
        ledger = _create(svc)
        with pytest.raises(LedgerTenantError):
            svc.current(str(ledger.ledger_id), tenant_id=OTHER_TENANT)

    def test_cross_tenant_append_denied(self):
        svc = _svc()
        ledger = _create(svc)
        with pytest.raises(LedgerTenantError):
            svc.append(
                str(ledger.ledger_id),
                _make_entry(tenant_id=TENANT),
                actor="r1",
                tenant_id=OTHER_TENANT,
            )

    def test_cross_tenant_review_denied(self):
        svc = _svc()
        ledger = _create(svc)
        with pytest.raises(LedgerTenantError):
            svc.review(
                str(ledger.ledger_id), _approve_decision(), tenant_id=OTHER_TENANT
            )

    def test_no_private_cot_accepted(self):
        """LedgerEntry with is_private_cot=True must be rejected at construction."""
        with pytest.raises(
            LedgerValidationError, match="private model chain-of-thought"
        ):
            LedgerEntry(
                kind=LedgerEntryKind.SUPPORT,
                text="private thoughts",
                author="model",
                tenant_id=TENANT,
                project_id=PROJECT,
                is_private_cot=True,
            )

    def test_publish_blocked_without_conclusion(self):
        svc = _svc()
        ledger = _create(svc)
        lid = str(ledger.ledger_id)
        svc.append(lid, _make_entry(), actor="r1", tenant_id=TENANT)
        svc.review(lid, _approve_decision(), tenant_id=TENANT)

        with pytest.raises(LedgerPublicationError, match="CONCLUSION"):
            svc.publish(lid, tenant_id=TENANT)

    def test_publish_blocked_without_approval(self):
        svc = _svc()
        ledger = _create(svc)
        lid = str(ledger.ledger_id)
        svc.append(lid, _make_conclusion(), actor="r1", tenant_id=TENANT)

        with pytest.raises(LedgerPublicationError, match="approval"):
            svc.publish(lid, tenant_id=TENANT)

    def test_append_to_published_ledger_raises(self):
        svc = _svc()
        ledger = _build_publishable_ledger(svc)
        lid = str(ledger.ledger_id)
        svc.publish(lid, tenant_id=TENANT)

        with pytest.raises(LedgerValidationError, match="published"):
            svc.append(lid, _make_entry(), actor="r1", tenant_id=TENANT)
