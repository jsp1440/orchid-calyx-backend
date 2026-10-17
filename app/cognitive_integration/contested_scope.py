"""The reasoning operation applied to two reproductive reports that disagree.

Improvement Discovery filed the bee-orchid conflict as a *missing reasoning
operation*: evidence exists on both sides and nothing decided what to do with
it. This module is that operation, and its decision rule is deliberately narrow.

**Scope test, then an explicit decision to leave it contested.** Two
incompatible reports are compatible only when they are established to describe
separate ground: both name a structured region, and the graph declares those
regions disjoint with a cited ``disjoint_from`` edge. Every other case — a
missing scope on either side, the same region on both, two regions nothing
declares separate, or a declaration with no citation — is left *contested*, on purpose, with the reason recorded.

**No weighting rule.** Evidence state, source type and publication date are not
commensurable measures of which report is true for this taxon, and ranking them
would pick a scientific winner by arithmetic. So no weighting is applied, no
report is preferred, and both reports are always retained. The adjudication
records that choice rather than leaving it implied.

Like an improvement candidate, an adjudication is a record for a human
reviewer. It cannot mark itself reviewed, cannot name a winner, and cannot drop
a report; constructing one that does raises.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

OPERATION = "scope-disjointness-test"
OPERATION_VERSION = "1"

CONTESTED = "unresolved_presented_as_contested"
RESOLVED_BY_SCOPE = "resolved_by_scope"

#: The decision taken when the scope test does not separate the reports.
LEAVE_CONTESTED = "leave_contested"
COMPATIBLE_BY_SCOPE = "compatible_by_scope"

#: What older code wrote where a ``disjoint_from`` edge had no citation. It is a
#: placeholder, not a source, and it never counts as one.
NO_CITATION = "no citation recorded"


def is_citation(value: object) -> bool:
    """A usable citation: a non-blank string that is not the placeholder.

    The placeholder is truthy, so a bare truthiness check let an uncited
    disjointness declaration resolve a contradiction.
    """
    if not isinstance(value, str):
        return False
    text = value.strip()
    return bool(text) and text.casefold() != NO_CITATION


class ScopeReason(StrEnum):
    """Why the scope test reached its outcome. One per adjudication."""

    DISJOINT_DECLARED = "disjoint_regions_declared"
    SCOPE_ABSENT_BOTH = "scope_region_absent_on_both_reports"
    SCOPE_ABSENT_ONE = "scope_region_absent_on_one_report"
    SAME_REGION = "same_region_on_both_reports"
    DISJOINTNESS_NOT_ESTABLISHED = "regions_differ_but_disjointness_not_declared"
    DISJOINTNESS_UNCITED = "disjointness_declared_without_citation"


#: Reasons for which the graph carries a ``disjoint_from`` edge for the pair.
_DISJOINTNESS_PRESENT = frozenset(
    {ScopeReason.DISJOINT_DECLARED, ScopeReason.DISJOINTNESS_UNCITED}
)


#: What would have to be retrieved for the outcome to change. Stated per reason
#: so a reviewer sees the concrete evidence that is missing, not a generic plea.
_WOULD_CHANGE_IF: dict[ScopeReason, str] = {
    ScopeReason.DISJOINT_DECLARED: (
        "The cited disjointness of the two regions is withdrawn or shown to be "
        "wrong, which would return the reports to contested."
    ),
    ScopeReason.SCOPE_ABSENT_BOTH: (
        "Each report is tied to a structured region by its source, and the graph "
        "carries a cited declaration that those regions do not overlap."
    ),
    ScopeReason.SCOPE_ABSENT_ONE: (
        "The report without a structured region is tied to one by its source, and "
        "the graph carries a cited declaration that the two regions do not overlap."
    ),
    ScopeReason.SAME_REGION: (
        "Nothing about scope can change this: two incompatible reports about one "
        "region are a live conflict. Only evidence bearing on the reports "
        "themselves, assessed by a human reviewer, could."
    ),
    ScopeReason.DISJOINTNESS_NOT_ESTABLISHED: (
        "A cited source establishes that the two named regions do not overlap, "
        "recorded as a disjoint_from edge between them."
    ),
    ScopeReason.DISJOINTNESS_UNCITED: (
        "The disjoint_from declaration between the two named regions carries a "
        "citable source. An uncited declaration cannot remove a disagreement."
    ),
}


@dataclass(frozen=True)
class ScopeAdjudication:
    """The auditable outcome of the scope test for one conflicting pair."""

    between: tuple[str, str]
    reason: ScopeReason
    scope_region_declared: tuple[bool, bool]
    disjointness_declared: bool
    resolved_by: str | None
    operation: str = OPERATION
    operation_version: str = OPERATION_VERSION
    #: Invariants. Any of these relaxed would let the operation pick a winner,
    #: hide a report, or certify itself.
    weighting_applied: bool = False
    preferred_report: None = None
    reports_retained: int = 2
    requires_human_review: bool = True
    may_activate_scientific_conclusion: bool = False

    def __post_init__(self) -> None:
        if self.weighting_applied:
            raise ValueError(
                "SCOPE_TEST_NO_WEIGHTING: the scope test may not weight one report "
                "over another"
            )
        if self.preferred_report is not None:
            raise ValueError(
                "SCOPE_TEST_NO_WINNER: the scope test may not prefer either report"
            )
        if self.reports_retained != len(self.between) or len(self.between) != 2:
            raise ValueError(
                "SCOPE_TEST_RETAINS_BOTH: both conflicting reports must be retained"
            )
        if not self.requires_human_review or self.may_activate_scientific_conclusion:
            raise ValueError(
                "SCOPE_TEST_REVIEW_INVARIANT: an adjudication is a record for a human "
                "reviewer, not a scientific conclusion"
            )
        if (self.reason in _DISJOINTNESS_PRESENT) != self.disjointness_declared:
            raise ValueError(
                "SCOPE_TEST_DISJOINTNESS: only declared disjointness separates the reports"
            )
        if self.resolution == RESOLVED_BY_SCOPE and not is_citation(self.resolved_by):
            raise ValueError(
                "SCOPE_TEST_AUDIT: a scope resolution must cite what declared the "
                "regions separate"
            )
        if self.resolution == CONTESTED and self.resolved_by is not None:
            raise ValueError("SCOPE_TEST_AUDIT: a contested pair cites no resolution")

    @property
    def resolution(self) -> str:
        """The value the reasoning-map contract carries for this contradiction."""
        return (
            RESOLVED_BY_SCOPE
            if self.reason is ScopeReason.DISJOINT_DECLARED
            else CONTESTED
        )

    @property
    def decision(self) -> str:
        return (
            COMPATIBLE_BY_SCOPE
            if self.resolution == RESOLVED_BY_SCOPE
            else LEAVE_CONTESTED
        )

    def to_record(self) -> dict[str, Any]:
        data = asdict(self)
        data["between"] = list(self.between)
        data["scope_region_declared"] = list(self.scope_region_declared)
        data["reason"] = self.reason.value
        data["resolution"] = self.resolution
        data["decision"] = self.decision
        data["would_change_if"] = _WOULD_CHANGE_IF[self.reason]
        return data


def adjudicate(
    first: dict[str, Any],
    second: dict[str, Any],
    disjoint: set[frozenset[str]],
    provenance: dict[frozenset[str], str] | None = None,
) -> ScopeAdjudication:
    """Apply the scope test to two conflicting reports.

    Resolution requires *established* disjointness: both regions present, a
    ``disjoint_from`` edge for the pair, and a real citation for that edge.
    Anything short of it leaves
    the contradiction standing, which is the fail-closed direction: a conflict
    wrongly left open costs a reader some care, while one wrongly closed deletes
    a real scientific disagreement.
    """
    first_region = _region(first.get("scope_region"))
    second_region = _region(second.get("scope_region"))
    pair = frozenset({first_region, second_region})
    citation = (provenance or {}).get(pair)
    declared = (first_region is not None, second_region is not None)

    if not any(declared):
        reason = ScopeReason.SCOPE_ABSENT_BOTH
    elif not all(declared):
        reason = ScopeReason.SCOPE_ABSENT_ONE
    elif first_region == second_region:
        reason = ScopeReason.SAME_REGION
    elif pair not in disjoint:
        reason = ScopeReason.DISJOINTNESS_NOT_ESTABLISHED
    elif not is_citation(citation):
        # Declared but uncited: the one inference that deletes a disagreement
        # must be auditable, so without a source the pair stays contested.
        reason = ScopeReason.DISJOINTNESS_UNCITED
    else:
        reason = ScopeReason.DISJOINT_DECLARED

    resolved_by = citation.strip() if reason is ScopeReason.DISJOINT_DECLARED else None

    return ScopeAdjudication(
        between=(
            f"{first['predicate']} {first['object']}",
            f"{second['predicate']} {second['object']}",
        ),
        reason=reason,
        scope_region_declared=declared,
        disjointness_declared=reason in _DISJOINTNESS_PRESENT,
        resolved_by=resolved_by,
    )


def _region(value: object) -> str | None:
    """A structured region key, or ``None``. Blank or whitespace is absent."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None
