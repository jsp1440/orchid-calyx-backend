from collections.abc import Mapping, Sequence
from typing import Any


def require_provenance(provenance: Mapping[str, Any]) -> None:
    if not provenance or not any(value not in (None, "", [], {}) for value in provenance.values()):
        raise ValueError("PROVENANCE_INCOMPLETE")


def validate_resolution_state(method: str, status: str, term_id: int | None) -> None:
    if method == "UNRESOLVED" and term_id is not None:
        raise ValueError("UNRESOLVED_WITH_TERM")
    if status == "ACCEPTED" and term_id is None:
        raise ValueError("ACCEPTED_RESOLUTION_REQUIRES_TERM")


def validate_readiness_flags(flags: Mapping[str, bool], blockers: Sequence[str]) -> None:
    required = ("evidence_complete", "ontology_resolved", "review_complete", "provenance_complete")
    expected = all(flags.get(item, False) for item in required) and not blockers
    if flags.get("ready_for_publication", False) != expected:
        raise ValueError("INVALID_READINESS_STATE")


def ensure_no_hierarchy_cycle(term_id: int | None, parent_id: int | None, ancestors: Sequence[int]) -> None:
    if term_id is not None and parent_id == term_id:
        raise ValueError("ONTOLOGY_SELF_PARENT")
    if term_id is not None and term_id in ancestors:
        raise ValueError("ONTOLOGY_HIERARCHY_CYCLE")


def validate_evidence_hash(expected: str, actual: str) -> None:
    if expected != actual:
        raise ValueError("EVIDENCE_HASH_MISMATCH")
