"""LEARN stage: versioned cognition inputs with provenance and content hashes.

The evolve loop may only reason over *versioned* inputs.  A cognition item that
cannot name its origin, its version, and a stable reference is rejected; the
loop fails closed rather than silently experimenting against an unknown
baseline.

Cognition items deliberately carry only concise, inspectable summaries.  Full
provider transcripts and private chain-of-thought are never accepted (see
:func:`runtime.calyx_evolve.redaction.assert_inspectable`).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from runtime.calyx_evolve.provenance import content_hash
from runtime.calyx_evolve.redaction import assert_inspectable

#: Cognition kinds accepted by the LEARN stage.
KIND_SOURCE_RELEASE = "source_release"
KIND_EXPERT_RULE = "expert_rule"
KIND_PRIOR_EXPERIMENT = "prior_experiment_summary"
KIND_EVALUATOR_VERSION = "evaluator_version"

COGNITION_KINDS: frozenset[str] = frozenset(
    {
        KIND_SOURCE_RELEASE,
        KIND_EXPERT_RULE,
        KIND_PRIOR_EXPERIMENT,
        KIND_EVALUATOR_VERSION,
    }
)

#: Kinds a campaign cannot start without.
REQUIRED_KINDS: frozenset[str] = frozenset({KIND_SOURCE_RELEASE, KIND_EVALUATOR_VERSION})

#: Provenance fields every cognition item must supply.
REQUIRED_PROVENANCE_FIELDS: tuple[str, ...] = ("origin", "reference", "recorded_at")

#: Maximum characters retained for a cognition summary.
SUMMARY_MAX_CHARS = 600


class CognitionError(ValueError):
    """Base class for LEARN-stage rejections."""


class UnknownCognitionKind(CognitionError):
    pass


class MissingProvenance(CognitionError):
    pass


class MissingRequiredCognition(CognitionError):
    pass


@dataclass(frozen=True, slots=True)
class CognitionItem:
    """One versioned input the loop is permitted to learn from."""

    item_id: str
    kind: str
    version: str
    summary: str
    provenance: Mapping[str, Any]
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in COGNITION_KINDS:
            raise UnknownCognitionKind(
                f"cognition kind {self.kind!r} is not one of {sorted(COGNITION_KINDS)}"
            )
        if not str(self.item_id).strip():
            raise CognitionError("cognition item_id is required")
        if not str(self.version).strip():
            raise MissingProvenance(f"cognition item {self.item_id!r} has no version")
        missing = [
            name
            for name in REQUIRED_PROVENANCE_FIELDS
            if not str((self.provenance or {}).get(name, "")).strip()
        ]
        if missing:
            raise MissingProvenance(
                f"cognition item {self.item_id!r} is missing provenance fields: {sorted(missing)}"
            )
        if len(self.summary) > SUMMARY_MAX_CHARS:
            raise CognitionError(
                f"cognition summary for {self.item_id!r} exceeds {SUMMARY_MAX_CHARS} characters; "
                "store a concise summary, not a transcript"
            )
        assert_inspectable({"summary": self.summary, "payload": dict(self.payload)})

    @property
    def content_hash(self) -> str:
        return content_hash(self.to_dict(include_hash=False))

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        record: dict[str, Any] = {
            "item_id": self.item_id,
            "kind": self.kind,
            "version": self.version,
            "summary": self.summary,
            "provenance": dict(self.provenance),
            "payload": dict(self.payload),
        }
        if include_hash:
            record["content_hash"] = self.content_hash
        return record


@dataclass(frozen=True, slots=True)
class CognitionBundle:
    """The full, ordered set of cognition inputs for one campaign cycle."""

    items: tuple[CognitionItem, ...]

    @property
    def bundle_hash(self) -> str:
        return content_hash([item.content_hash for item in self.items])

    def kinds(self) -> frozenset[str]:
        return frozenset(item.kind for item in self.items)

    def by_kind(self, kind: str) -> tuple[CognitionItem, ...]:
        return tuple(item for item in self.items if item.kind == kind)

    def require(self, kind: str) -> CognitionItem:
        matches = self.by_kind(kind)
        if not matches:
            raise MissingRequiredCognition(f"no cognition item of kind {kind!r}")
        return matches[0]

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle_hash": self.bundle_hash,
            "item_count": len(self.items),
            "kinds": sorted(self.kinds()),
            "items": [item.to_dict() for item in self.items],
        }


def load_cognition(items: Iterable[CognitionItem]) -> CognitionBundle:
    """Validate and order cognition inputs, failing closed on gaps.

    Items are sorted by ``(kind, item_id)`` so that the bundle hash does not
    depend on caller ordering.  Duplicate ``item_id`` values are rejected: the
    loop must not learn the same input twice under two versions in one cycle.
    """

    ordered = sorted(items, key=lambda item: (item.kind, item.item_id))
    seen: set[str] = set()
    for item in ordered:
        if item.item_id in seen:
            raise CognitionError(f"duplicate cognition item_id {item.item_id!r}")
        seen.add(item.item_id)

    bundle = CognitionBundle(tuple(ordered))
    missing = sorted(REQUIRED_KINDS - bundle.kinds())
    if missing:
        raise MissingRequiredCognition(
            f"campaign cannot LEARN without cognition kinds: {missing}"
        )
    return bundle
