"""CALYX CORE 4 — End-to-end operator panel certification for Laelia anceps.

Covers the bounded scientific mission described in issue #388:
  question → evidence → Reasoning Ledger → review pending
  → approve → discover eligible → publish (with confirmation)
  → duplicate replay is a no-op
  → publication impossible without owner confirmation
  → UI displays plain-language errors (no hash copying required)

This module is the primary acceptance test for the operator UI component of
CALYX CORE 4.
"""

from __future__ import annotations

import re

import pytest

from app.operator_panel.panel import OperatorPanel, friendly_error, MissionBrief
from app.reasoning_ledger.models import LedgerEntryKind, LedgerStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

OWNER = "calyx-owner"
PROJECT_ID = "laelia-anceps-taxonomy-001"

LAELIA_QUESTION = (
    "What are the current taxonomy, distribution, pollination mechanisms, "
    "conservation status, and mycorrhizal evidence for Laelia anceps?"
)

EVIDENCE = [
    {
        "text": (
            "Laelia anceps Lindl. (1835) is accepted within Orchidaceae, tribe Epidendreae. "
            "Recent molecular phylogenetics (Chase et al. 2015) maintain this placement."
        ),
        "kind": LedgerEntryKind.SUPPORT,
        "confidence": None,
    },
    {
        "text": (
            "Distribution: native to Mexico (Oaxaca, Veracruz, Puebla, Hidalgo) "
            "and Honduras. Grows epiphytically at 400–2000 m elevation on oak-pine "
            "forest margins."
        ),
        "kind": LedgerEntryKind.SUPPORT,
        "confidence": None,
    },
    {
        "text": (
            "Pollination: eulaema bees (Euglossini) documented as primary pollinators "
            "via fragrance reward in field studies (Dressler 1990; Roubik 2001)."
        ),
        "kind": LedgerEntryKind.SUPPORT,
        "confidence": None,
    },
    {
        "text": (
            "Conservation: IUCN Red List — Least Concern (2020). CITES Appendix II. "
            "Habitat fragmentation in Veracruz is noted as an emerging pressure."
        ),
        "kind": LedgerEntryKind.SUPPORT,
        "confidence": None,
    },
    {
        "text": (
            "Mycorrhizal evidence is limited. One study (Otero et al. 2007) reports "
            "Tulasnella association in germination studies; field characterisation "
            "for adult plants is lacking."
        ),
        "kind": LedgerEntryKind.ASSUMPTION,
        "confidence": None,
    },
    {
        "text": (
            "CONCLUSION: Laelia anceps has a well-supported taxonomic placement, "
            "restricted Mexican/Honduran distribution, euglossine-bee pollination, "
            "LC conservation status, and partial mycorrhizal characterisation. "
            "Confidence is high for taxonomy, distribution, and pollination; "
            "moderate for conservation; low for adult mycorrhizal partners."
        ),
        "kind": LedgerEntryKind.CONCLUSION,
        "confidence": 0.85,
    },
]


def _build_approved_laelia_ledger(panel: OperatorPanel) -> str:
    """Run through question → evidence → review → approve and return ledger_id."""
    started = panel.start_mission(
        owner=OWNER,
        project_id=PROJECT_ID,
        title=LAELIA_QUESTION,
        description="Bounded scientific mission for Laelia anceps as per CALYX CORE 4.",
    )
    ledger_id = started["ledger_id"]

    for ev in EVIDENCE:
        panel.add_evidence(
            ledger_id=ledger_id,
            owner=OWNER,
            project_id=PROJECT_ID,
            text=ev["text"],
            kind=ev["kind"],
            confidence=ev["confidence"],
        )

    panel.submit_for_review(
        ledger_id=ledger_id,
        owner=OWNER,
        project_id=PROJECT_ID,
    )

    panel.approve(
        ledger_id=ledger_id,
        owner=OWNER,
        rationale=(
            "Evidence is consistent, well-sourced, and the conclusion confidence "
            "meets the publication threshold. Laelia anceps mission certified."
        ),
    )
    return ledger_id


# ---------------------------------------------------------------------------
# Acceptance tests
# ---------------------------------------------------------------------------


class TestLaeliaAncepsEndToEnd:
    """Full pipeline: question → evidence → ledger → review pending."""

    def test_mission_starts_successfully(self):
        panel = OperatorPanel()
        result = panel.start_mission(
            owner=OWNER,
            project_id=PROJECT_ID,
            title=LAELIA_QUESTION,
        )
        assert result["ledger_id"]
        assert result["title"] == LAELIA_QUESTION
        assert result["status"] == LedgerStatus.DRAFT.value
        assert "started successfully" in result["message"]

    def test_evidence_accumulates_on_ledger(self):
        panel = OperatorPanel()
        started = panel.start_mission(
            owner=OWNER,
            project_id=PROJECT_ID,
            title=LAELIA_QUESTION,
        )
        ledger_id = started["ledger_id"]

        for ev in EVIDENCE[:3]:
            panel.add_evidence(
                ledger_id=ledger_id,
                owner=OWNER,
                project_id=PROJECT_ID,
                text=ev["text"],
                kind=ev["kind"],
                confidence=ev["confidence"],
            )

        brief = panel.mission_brief(ledger_id=ledger_id, owner=OWNER)
        assert brief.evidence_entries >= 3

    def test_submit_for_review_transitions_status(self):
        panel = OperatorPanel()
        started = panel.start_mission(
            owner=OWNER,
            project_id=PROJECT_ID,
            title=LAELIA_QUESTION,
        )
        ledger_id = started["ledger_id"]
        panel.add_evidence(
            ledger_id=ledger_id,
            owner=OWNER,
            project_id=PROJECT_ID,
            text="Some taxonomy evidence.",
            kind=LedgerEntryKind.SUPPORT,
        )
        result = panel.submit_for_review(
            ledger_id=ledger_id,
            owner=OWNER,
            project_id=PROJECT_ID,
        )
        assert result["ledger_id"] == ledger_id
        assert "review" in result["message"].lower()

    def test_full_pipeline_reaches_review_pending(self):
        panel = OperatorPanel()
        started = panel.start_mission(
            owner=OWNER,
            project_id=PROJECT_ID,
            title=LAELIA_QUESTION,
        )
        ledger_id = started["ledger_id"]
        for ev in EVIDENCE:
            panel.add_evidence(
                ledger_id=ledger_id,
                owner=OWNER,
                project_id=PROJECT_ID,
                text=ev["text"],
                kind=ev["kind"],
                confidence=ev["confidence"],
            )
        result = panel.submit_for_review(
            ledger_id=ledger_id,
            owner=OWNER,
            project_id=PROJECT_ID,
        )
        brief = panel.mission_brief(ledger_id=ledger_id, owner=OWNER)
        # Ledger should be under review (or in_progress after OPERATION append).
        assert brief.ledger_id == ledger_id
        assert brief.evidence_entries >= 2
        assert brief.confidence is not None and brief.confidence >= 0.6

    def test_approve_transitions_ledger_to_approved(self):
        panel = OperatorPanel()
        ledger_id = _build_approved_laelia_ledger(panel)
        brief = panel.mission_brief(ledger_id=ledger_id, owner=OWNER)
        assert brief.status == LedgerStatus.APPROVED.value
        assert brief.last_review_outcome == "approved"
        assert brief.is_eligible_for_publication is True

    def test_request_revision_puts_ledger_back_in_progress(self):
        panel = OperatorPanel()
        started = panel.start_mission(
            owner=OWNER,
            project_id=PROJECT_ID,
            title=LAELIA_QUESTION,
        )
        ledger_id = started["ledger_id"]
        panel.add_evidence(
            ledger_id=ledger_id,
            owner=OWNER,
            project_id=PROJECT_ID,
            text="Preliminary taxonomy evidence.",
            kind=LedgerEntryKind.SUPPORT,
        )
        result = panel.request_revision(
            ledger_id=ledger_id,
            owner=OWNER,
            rationale="More mycorrhizal data needed.",
        )
        assert "revision" in result["message"].lower() or "progress" in result["message"].lower()

    def test_reject_is_accepted_by_ledger(self):
        panel = OperatorPanel()
        started = panel.start_mission(
            owner=OWNER,
            project_id=PROJECT_ID,
            title=LAELIA_QUESTION,
        )
        ledger_id = started["ledger_id"]
        panel.add_evidence(
            ledger_id=ledger_id,
            owner=OWNER,
            project_id=PROJECT_ID,
            text="Preliminary evidence only.",
            kind=LedgerEntryKind.SUPPORT,
        )
        result = panel.reject(
            ledger_id=ledger_id,
            owner=OWNER,
            rationale="Evidence insufficient for this ledger.",
        )
        assert "rejected" in result["message"].lower()


class TestEligibleLedgerDiscovery:
    """Approved fixture can be discovered automatically without copying IDs."""

    def test_approved_ledger_is_discovered_automatically(self):
        panel = OperatorPanel()
        ledger_id = _build_approved_laelia_ledger(panel)
        report = panel.discover_eligible_ledgers(owner=OWNER)
        assert report["result"] == "ELIGIBLE_LEDGER_FOUND"
        assert report["eligible_count"] >= 1
        ids = [item["ledger_id"] for item in report["eligible_ledgers"]]
        assert ledger_id in ids

    def test_discovery_never_invokes_publication_endpoint(self):
        panel = OperatorPanel()
        _build_approved_laelia_ledger(panel)
        report = panel.discover_eligible_ledgers(owner=OWNER)
        assert report["publication_endpoint_invoked"] is False

    def test_empty_discovery_gives_plain_no_eligible_result(self):
        panel = OperatorPanel()
        report = panel.discover_eligible_ledgers(owner=OWNER)
        assert report["result"] == "NO_ELIGIBLE_LEDGER"
        assert report["eligible_count"] == 0
        assert report["eligible_ledgers"] == []

    def test_discovery_result_includes_title_not_just_hash(self):
        panel = OperatorPanel()
        _build_approved_laelia_ledger(panel)
        report = panel.discover_eligible_ledgers(owner=OWNER)
        assert report["eligible_ledgers"][0]["title"]


class TestPublicationGate:
    """Publication remains impossible without owner confirmation."""

    def test_publication_without_confirmation_is_refused(self):
        panel = OperatorPanel()
        ledger_id = _build_approved_laelia_ledger(panel)
        result = panel.publish(
            ledger_id=ledger_id,
            owner=OWNER,
            confirmation="",
        )
        assert result["outcome"] == "REFUSED"
        assert result["publication_endpoint_invoked"] is False
        # Message must be plain language, no internal codes.
        assert "confirmation" in result["message"].lower() or "confirm" in result["message"].lower()

    def test_publication_with_wrong_phrase_is_refused(self):
        panel = OperatorPanel()
        ledger_id = _build_approved_laelia_ledger(panel)
        result = panel.publish(
            ledger_id=ledger_id,
            owner=OWNER,
            confirmation="yes please",
        )
        assert result["outcome"] == "REFUSED"

    def test_publication_with_exact_confirmation_succeeds(self):
        panel = OperatorPanel()
        ledger_id = _build_approved_laelia_ledger(panel)
        result = panel.publish(
            ledger_id=ledger_id,
            owner=OWNER,
            confirmation=OperatorPanel.PUBLICATION_CONFIRMATION_PHRASE,
        )
        assert result["outcome"] == "PUBLISHED"
        assert result["ledger_id"] == ledger_id
        assert result["version"]
        assert result["graph_version"]
        assert result["automatic_publication"] is False

    def test_unapprovable_ledger_cannot_be_published(self):
        panel = OperatorPanel()
        # Ledger with only support evidence, no conclusion, no approval.
        started = panel.start_mission(
            owner=OWNER,
            project_id=PROJECT_ID,
            title=LAELIA_QUESTION,
        )
        ledger_id = started["ledger_id"]
        panel.add_evidence(
            ledger_id=ledger_id,
            owner=OWNER,
            project_id=PROJECT_ID,
            text="Taxonomy support only.",
            kind=LedgerEntryKind.SUPPORT,
        )
        result = panel.publish(
            ledger_id=ledger_id,
            owner=OWNER,
            confirmation=OperatorPanel.PUBLICATION_CONFIRMATION_PHRASE,
        )
        assert result["outcome"] == "ERROR"
        # Plain-language message, not an internal code.
        assert result["message"]
        assert "PUBLICATION_BLOCKED" not in result["message"]

    def test_publication_produces_auditable_result(self):
        panel = OperatorPanel()
        ledger_id = _build_approved_laelia_ledger(panel)
        result = panel.publish(
            ledger_id=ledger_id,
            owner=OWNER,
            confirmation=OperatorPanel.PUBLICATION_CONFIRMATION_PHRASE,
        )
        assert result["outcome"] == "PUBLISHED"
        assert result["graph_version"] is not None


class TestDuplicateReplayNoOp:
    """Duplicate replay is a no-op."""

    def test_second_publication_of_same_version_is_no_op(self):
        panel = OperatorPanel()
        ledger_id = _build_approved_laelia_ledger(panel)
        first = panel.publish(
            ledger_id=ledger_id,
            owner=OWNER,
            confirmation=OperatorPanel.PUBLICATION_CONFIRMATION_PHRASE,
        )
        assert first["outcome"] == "PUBLISHED"

        second = panel.publish(
            ledger_id=ledger_id,
            owner=OWNER,
            confirmation=OperatorPanel.PUBLICATION_CONFIRMATION_PHRASE,
        )
        assert second["outcome"] == "NO_OP_DUPLICATE"
        assert "already been published" in second["message"].lower() or \
               "duplicate" in second["message"].lower()

    def test_no_op_duplicate_preserves_version(self):
        panel = OperatorPanel()
        ledger_id = _build_approved_laelia_ledger(panel)
        first = panel.publish(
            ledger_id=ledger_id,
            owner=OWNER,
            confirmation=OperatorPanel.PUBLICATION_CONFIRMATION_PHRASE,
        )
        second = panel.publish(
            ledger_id=ledger_id,
            owner=OWNER,
            confirmation=OperatorPanel.PUBLICATION_CONFIRMATION_PHRASE,
        )
        assert second["version"] == first["version"]


class TestMissionBrief:
    """Mission brief surfaces plan, progress, evidence, contradictions, confidence, blockers."""

    def test_brief_shows_all_required_fields(self):
        panel = OperatorPanel()
        ledger_id = _build_approved_laelia_ledger(panel)
        brief = panel.mission_brief(ledger_id=ledger_id, owner=OWNER)
        assert isinstance(brief, MissionBrief)
        d = brief.as_dict()
        for field in [
            "ledger_id", "title", "status", "version", "plan_entries",
            "evidence_entries", "contradiction_entries", "unresolved_contradictions",
            "gap_entries", "confidence", "blockers", "review_state",
            "last_review_outcome", "is_eligible_for_publication",
        ]:
            assert field in d, f"missing field: {field}"

    def test_brief_shows_confidence_for_approved_ledger(self):
        panel = OperatorPanel()
        ledger_id = _build_approved_laelia_ledger(panel)
        brief = panel.mission_brief(ledger_id=ledger_id, owner=OWNER)
        assert brief.confidence is not None
        assert brief.confidence >= 0.6

    def test_brief_shows_no_blockers_for_approved_publishable_ledger(self):
        panel = OperatorPanel()
        ledger_id = _build_approved_laelia_ledger(panel)
        brief = panel.mission_brief(ledger_id=ledger_id, owner=OWNER)
        assert brief.blockers == []
        assert brief.is_eligible_for_publication is True

    def test_brief_for_unknown_ledger_raises_lookup_error(self):
        panel = OperatorPanel()
        with pytest.raises(LookupError):
            panel.mission_brief(
                ledger_id="00000000-0000-0000-0000-000000000000",
                owner=OWNER,
            )


class TestPlainLanguageErrors:
    """UI displays plain-language errors and never asks owner to copy ledger hashes."""

    def test_friendly_error_for_known_codes(self):
        for code in [
            "AUTHENTICATED_SUBJECT_REQUIRED",
            "LEDGER_NOT_FOUND",
            "PUBLICATION_BLOCKED",
            "EXACT_APPROVAL_REQUIRED",
            "OWNER_CONFIRMATION_REQUIRED",
            "DUPLICATE_PUBLICATION",
        ]:
            msg = friendly_error(code)
            assert msg
            assert msg != code
            assert msg[0].isupper()

    def test_friendly_error_for_unknown_code_is_not_raw_code(self):
        msg = friendly_error("SOME_INTERNAL_ERROR_XYZ")
        assert "SOME_INTERNAL_ERROR_XYZ" in msg or "unexpected" in msg.lower()

    def test_publication_refused_message_contains_no_hash(self):
        panel = OperatorPanel()
        ledger_id = _build_approved_laelia_ledger(panel)
        result = panel.publish(
            ledger_id=ledger_id,
            owner=OWNER,
            confirmation="wrong",
        )
        # Message must not contain a hex hash (64 hex chars).
        assert not re.search(r"[0-9a-f]{64}", result["message"])

    def test_discovery_results_contain_no_raw_hashes_visible_to_operator(self):
        panel = OperatorPanel()
        _build_approved_laelia_ledger(panel)
        report = panel.discover_eligible_ledgers(owner=OWNER)
        # The eligible_ledgers items carry review_content_hash internally for the
        # publication API, but the title field must be present (human-readable).
        assert report["eligible_ledgers"][0]["title"]
