"""Generation, persistence and review logic for the field hypothesis loop.

Persistence reuses the Research Station record store
(:mod:`runtime.research_station_store`) rather than adding tables: one JSON
record table keyed by ``(owner_key, project_id, kind, record_id)``. Here
``owner_key`` is this module's namespace, ``project_id`` is the observation id,
and ``kind`` distinguishes sets, evidence, reviews and the id index.

Identity is content-derived so retries are idempotent: the same observation
snapshot yields the same set and hypothesis ids, and the same evidence item
yields the same evidence id, whichever store is live.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from runtime.research_station_store import (
    MemoryProjectRecordStore,
    ProjectRecordStore,
    build_record_store,
)

from . import library
from .schemas import (
    MINIMUM_COMPETING_HYPOTHESES,
    EvidenceBalance,
    EvidenceRecordIn,
    EvidenceRecordOut,
    EvidenceStance,
    EvidenceState,
    GenerationProvenance,
    HumanReview,
    HypothesisOut,
    HypothesisSetOut,
    HypothesisStatus,
    LibraryOut,
    LibraryTemplateOut,
    ObservationSnapshot,
    ObservationSummary,
    ReviewDecisionIn,
    ReviewState,
)

OWNER_KEY = "field-hypotheses"
INDEX_PROJECT = "_index"

KIND_SET = "field_hypothesis_set"
KIND_LATEST = "field_hypothesis_latest"
KIND_EVIDENCE = "field_hypothesis_evidence"
KIND_REVIEW = "field_hypothesis_review"
KIND_HYPOTHESIS_INDEX = "field_hypothesis_index"


class HypothesisNotFound(LookupError):
    pass


class HypothesisSetNotFound(LookupError):
    pass


def _stable(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:20]


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def observation_fingerprint(snapshot: ObservationSnapshot) -> str:
    return hashlib.sha256(_stable(snapshot.model_dump(mode="json")).encode("utf-8")).hexdigest()


def derive_evidence_state(balance: EvidenceBalance) -> EvidenceState:
    if balance.supporting and balance.contradicting:
        return EvidenceState.CONFLICTING
    if balance.supporting:
        return EvidenceState.SUPPORTING_ONLY
    if balance.contradicting:
        return EvidenceState.CONTRADICTING_ONLY
    if balance.unknown:
        return EvidenceState.UNKNOWN_ONLY
    return EvidenceState.NO_EVIDENCE


# Store wiring -----------------------------------------------------------------

_store: ProjectRecordStore | None = None


def configure_store(store: ProjectRecordStore | None) -> None:
    """Inject a store (tests pass a :class:`MemoryProjectRecordStore`); ``None`` resets."""
    global _store
    _store = store


def get_store() -> ProjectRecordStore:
    global _store
    if _store is None:
        _store = build_record_store()
    return _store


def memory_store() -> MemoryProjectRecordStore:
    return MemoryProjectRecordStore()


# Service ------------------------------------------------------------------------


class FieldHypothesisService:
    def __init__(self, store: ProjectRecordStore) -> None:
        self._store = store

    # -- generation -------------------------------------------------------

    def generate(self, observation_id: str, snapshot: ObservationSnapshot) -> HypothesisSetOut:
        fingerprint = observation_fingerprint(snapshot)
        set_id = _digest(observation_id, fingerprint, library.LIBRARY_VERSION)

        existing = self._store.get(
            owner_key=OWNER_KEY, project_id=observation_id, kind=KIND_SET, record_id=set_id
        )
        if existing is not None:
            return self._assemble_set(existing, created=False)

        selected = library.select_hypotheses(snapshot)
        if len(selected) < MINIMUM_COMPETING_HYPOTHESES:
            # The library guarantees this cannot happen; refuse to persist a
            # single-explanation set rather than silently emit one.
            raise RuntimeError("hypothesis library produced fewer than two competing hypotheses")

        generated_at = _now()
        hypotheses: list[dict[str, Any]] = []
        for item in selected:
            hypothesis_id = _digest(set_id, item.template.template_id)
            hypotheses.append(
                {
                    "hypothesis_id": hypothesis_id,
                    "template_id": item.template.template_id,
                    "hypothesis_class": item.template.hypothesis_class.value,
                    "ko_0038_strategy": item.template.ko_0038_strategy,
                    "statement": item.template.render_statement(snapshot),
                    "predictions": list(item.template.predictions),
                    "would_support": list(item.template.would_support),
                    "would_contradict": list(item.template.would_contradict),
                    "cue_matches": list(item.cue_matches),
                    "structural_alternative": item.structural,
                    "question_family_ids": list(item.template.question_family_ids),
                }
            )
            self._store.put(
                owner_key=OWNER_KEY,
                project_id=INDEX_PROJECT,
                kind=KIND_HYPOTHESIS_INDEX,
                record_id=hypothesis_id,
                record={"observation_id": observation_id, "set_id": set_id},
            )

        record = {
            "set_id": set_id,
            "observation_id": observation_id,
            "observation_fingerprint": fingerprint,
            "generated_at": generated_at.isoformat(),
            "generation": GenerationProvenance(
                library_version=library.LIBRARY_VERSION,
                basis=library.LIBRARY_BASIS,
                cue_tokens=library.cue_tokens(snapshot),
            ).model_dump(mode="json"),
            "observation": ObservationSummary(
                observer_id=snapshot.observer_id,
                observed_at=snapshot.observed_at,
                taxon_hint=snapshot.taxon_hint,
                epistemic_certainty=snapshot.epistemic_certainty,
                locality_sensitivity=snapshot.locality_sensitivity,
                media_count=len(snapshot.media_content_hashes),
            ).model_dump(mode="json"),
            "hypotheses": hypotheses,
            "follow_up_protocol": [
                fu.model_dump(mode="json") for fu in library.follow_up_protocol(selected)
            ],
            "protocol_constraints": list(library.PROTOCOL_CONSTRAINTS),
        }
        self._store.put(
            owner_key=OWNER_KEY,
            project_id=observation_id,
            kind=KIND_SET,
            record_id=set_id,
            record=record,
        )
        self._store.put(
            owner_key=OWNER_KEY,
            project_id=observation_id,
            kind=KIND_LATEST,
            record_id="latest",
            record={"set_id": set_id, "updated_at": generated_at.isoformat()},
        )
        return self._assemble_set(record, created=True)

    def latest_set(self, observation_id: str) -> HypothesisSetOut:
        pointer = self._store.get(
            owner_key=OWNER_KEY, project_id=observation_id, kind=KIND_LATEST, record_id="latest"
        )
        if pointer is None:
            raise HypothesisSetNotFound(observation_id)
        record = self._store.get(
            owner_key=OWNER_KEY,
            project_id=observation_id,
            kind=KIND_SET,
            record_id=str(pointer["set_id"]),
        )
        if record is None:
            raise HypothesisSetNotFound(observation_id)
        return self._assemble_set(record, created=False)

    # -- hypotheses ---------------------------------------------------------

    def get_hypothesis(self, hypothesis_id: str) -> HypothesisOut:
        observation_id, record, base = self._locate(hypothesis_id)
        return self._assemble_hypothesis(observation_id, record["set_id"], base)

    def record_evidence(self, hypothesis_id: str, payload: EvidenceRecordIn) -> HypothesisOut:
        observation_id, record, base = self._locate(hypothesis_id)
        evidence_id = _digest(
            hypothesis_id,
            payload.stance.value,
            payload.evidence_type.value,
            payload.summary,
            payload.source_kind.value,
            payload.source_reference or "",
            payload.recorder_subject,
        )
        if (
            self._store.get(
                owner_key=OWNER_KEY,
                project_id=observation_id,
                kind=KIND_EVIDENCE,
                record_id=evidence_id,
            )
            is None
        ):
            self._store.put(
                owner_key=OWNER_KEY,
                project_id=observation_id,
                kind=KIND_EVIDENCE,
                record_id=evidence_id,
                record={
                    "evidence_id": evidence_id,
                    "hypothesis_id": hypothesis_id,
                    "recorded_at": _now().isoformat(),
                    **payload.model_dump(mode="json"),
                },
            )
        return self._assemble_hypothesis(observation_id, record["set_id"], base)

    def review(self, hypothesis_id: str, decision: ReviewDecisionIn, actor: dict[str, Any]) -> HypothesisOut:
        observation_id, record, base = self._locate(hypothesis_id)
        self._store.put(
            owner_key=OWNER_KEY,
            project_id=observation_id,
            kind=KIND_REVIEW,
            record_id=hypothesis_id,
            record={
                "hypothesis_id": hypothesis_id,
                "status": decision.status.value,
                "review_state": decision.review_state.value,
                "rationale": decision.rationale,
                "refined_statement": decision.refined_statement,
                "actor": str(actor.get("actor") or actor.get("owner") or "authenticated"),
                "auth_type": str(actor.get("auth_type") or "owner_session"),
                "reviewed_at": _now().isoformat(),
            },
        )
        return self._assemble_hypothesis(observation_id, record["set_id"], base)

    # -- library --------------------------------------------------------------

    @staticmethod
    def library_listing() -> LibraryOut:
        return LibraryOut(
            library_version=library.LIBRARY_VERSION,
            basis=library.LIBRARY_BASIS,
            question_families=list(library.QUESTION_FAMILIES),
            templates=[
                LibraryTemplateOut(
                    template_id=template.template_id,
                    hypothesis_class=template.hypothesis_class,
                    ko_0038_strategy=template.ko_0038_strategy,
                    statement_template=template.statement,
                    positive_cues=sorted(template.positive_cues),
                    question_family_ids=list(template.question_family_ids),
                    always_included_when=list(template.always_included_when),
                )
                for template in library.TEMPLATES
            ],
            protocol_constraints=list(library.PROTOCOL_CONSTRAINTS),
        )

    # -- assembly -------------------------------------------------------------

    def _locate(self, hypothesis_id: str) -> tuple[str, dict[str, Any], dict[str, Any]]:
        index = self._store.get(
            owner_key=OWNER_KEY,
            project_id=INDEX_PROJECT,
            kind=KIND_HYPOTHESIS_INDEX,
            record_id=hypothesis_id,
        )
        if index is None:
            raise HypothesisNotFound(hypothesis_id)
        observation_id = str(index["observation_id"])
        record = self._store.get(
            owner_key=OWNER_KEY,
            project_id=observation_id,
            kind=KIND_SET,
            record_id=str(index["set_id"]),
        )
        if record is None:
            raise HypothesisNotFound(hypothesis_id)
        for base in record["hypotheses"]:
            if base["hypothesis_id"] == hypothesis_id:
                return observation_id, record, base
        raise HypothesisNotFound(hypothesis_id)

    def _evidence_for(self, observation_id: str, hypothesis_id: str) -> list[EvidenceRecordOut]:
        rows = self._store.list(owner_key=OWNER_KEY, project_id=observation_id, kind=KIND_EVIDENCE)
        items = [
            EvidenceRecordOut(
                evidence_id=row["evidence_id"],
                hypothesis_id=row["hypothesis_id"],
                stance=EvidenceStance(row["stance"]),
                evidence_type=row["evidence_type"],
                summary=row["summary"],
                source_kind=row["source_kind"],
                source_reference=row.get("source_reference"),
                recorder_subject=row["recorder_subject"],
                recorded_at=datetime.fromisoformat(row["recorded_at"]),
                created=False,
            )
            for row in rows
            if row.get("hypothesis_id") == hypothesis_id
        ]
        items.sort(key=lambda item: (item.recorded_at, item.evidence_id))
        return items

    def _assemble_hypothesis(
        self, observation_id: str, set_id: str, base: dict[str, Any]
    ) -> HypothesisOut:
        hypothesis_id = base["hypothesis_id"]
        evidence = self._evidence_for(observation_id, hypothesis_id)
        balance = EvidenceBalance(
            supporting=sum(1 for e in evidence if e.stance == EvidenceStance.SUPPORTING),
            contradicting=sum(1 for e in evidence if e.stance == EvidenceStance.CONTRADICTING),
            unknown=sum(1 for e in evidence if e.stance == EvidenceStance.UNKNOWN),
        )
        status = HypothesisStatus.UNDER_EVALUATION if evidence else HypothesisStatus.PROPOSED
        review_state = ReviewState.MACHINE_ASSISTED
        statement = base["statement"]
        human_review: HumanReview | None = None

        review = self._store.get(
            owner_key=OWNER_KEY, project_id=observation_id, kind=KIND_REVIEW, record_id=hypothesis_id
        )
        if review is not None:
            status = HypothesisStatus(review["status"])
            review_state = ReviewState(review["review_state"])
            if review.get("refined_statement"):
                statement = str(review["refined_statement"])
            human_review = HumanReview(
                actor=review["actor"],
                auth_type=review["auth_type"],
                rationale=review["rationale"],
                reviewed_at=datetime.fromisoformat(review["reviewed_at"]),
            )

        return HypothesisOut(
            hypothesis_id=hypothesis_id,
            set_id=set_id,
            observation_id=observation_id,
            template_id=base["template_id"],
            hypothesis_class=base["hypothesis_class"],
            ko_0038_strategy=base["ko_0038_strategy"],
            statement=statement,
            predictions=list(base["predictions"]),
            would_support=list(base["would_support"]),
            would_contradict=list(base["would_contradict"]),
            cue_matches=list(base["cue_matches"]),
            question_family_ids=list(base["question_family_ids"]),
            status=status,
            review_state=review_state,
            human_review=human_review,
            evidence_balance=balance,
            evidence_state=derive_evidence_state(balance),
            evidence=evidence,
        )

    def _assemble_set(self, record: dict[str, Any], *, created: bool) -> HypothesisSetOut:
        observation_id = record["observation_id"]
        set_id = record["set_id"]
        return HypothesisSetOut(
            set_id=set_id,
            observation_id=observation_id,
            observation_fingerprint=record["observation_fingerprint"],
            created=created,
            generated_at=datetime.fromisoformat(record["generated_at"]),
            generation=GenerationProvenance.model_validate(record["generation"]),
            observation=ObservationSummary.model_validate(record["observation"]),
            hypotheses=[
                self._assemble_hypothesis(observation_id, set_id, base)
                for base in record["hypotheses"]
            ],
            follow_up_protocol=record["follow_up_protocol"],
            protocol_constraints=list(record["protocol_constraints"]),
        )
