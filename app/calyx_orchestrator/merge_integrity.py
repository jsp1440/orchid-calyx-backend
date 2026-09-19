"""Prove that a merge landed the thing that was verified.

PR #706 was independently checked over five rounds, passed at `4efa379`, and
merged with `expectedHeadSha` naming that exact commit. The GitHub merge API
returned success. The squash produced the tree of `16cb85d`, three commits
behind, dropping 217 lines across four files.

Six regressions reached the integration branch. Five blanked scientific content
-- a lamp wattage erased an `environmental_notes` entry, a specimen identifier
was withheld as a coordinate, "a survey of 1961 records" read as an Ordnance
Survey grid reference. The sixth was a locality leak: a what3words address with
a trailing full stop reached the page at roughly three metres, under a footer
stating that no field had matched.

None of that was caught for twenty minutes, because the merge reported success
and nobody looked at the result.

``expectedHeadSha`` cannot catch this. It constrains *which commit is merged*,
not *what the squash produces from it*, so it was satisfied while the outcome
was wrong. The check that does catch it is cheap: compare the blob the
integration branch now holds against the blob the checker actually read, for
every path the change touched.

Scope, stated plainly: this proves the integration side holds what was verified
at the paths the caller declares. It says nothing about content the merge
*added* at paths nobody verified. It is built for the dropped-commit failure
class of #706, not for injection, and a lane must not read a `landed` verdict as
a statement about the rest of the tree.

Nothing here calls a provider, reads the network, or shells out. It takes
recorded facts and returns a verdict, so the decision is reproducible from the
record and testable without a repository.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

#: A git object id that has not been resolved. Treated as unusable evidence
#: rather than as a wildcard: an unknown blob never satisfies the invariant.
UNKNOWN = ""


class MergeVerdict(StrEnum):
    """What the post-merge inspection concluded."""

    #: Every verified path holds the verified content. Safe to record as landed.
    LANDED = "landed"
    #: The merge happened and the result is not what was verified. The lane
    #: stops here; this is the #706 failure.
    TREE_MISMATCH = "tree_mismatch"
    #: The merge API did not report success, so there is nothing to inspect.
    MERGE_NOT_REPORTED = "merge_not_reported"
    #: Not enough recorded evidence to decide. Never treated as success --
    #: reporting "integrated" on missing evidence is the habit that produced
    #: the incident.
    EVIDENCE_INCOMPLETE = "evidence_incomplete"


@dataclass(frozen=True, slots=True)
class VerifiedResult:
    """What an independent checker actually read, captured before the merge.

    ``blobs`` maps each path the change touches to its git blob id at the head
    the checker verified. A path the change deletes maps to ``None``; that is a
    claim about absence and is checked as strictly as a claim about content.
    """

    head_sha: str
    tree_sha: str
    blobs: dict[str, str | None] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.head_sha.strip():
            raise ValueError("VERIFIED_HEAD_REQUIRED")
        if not self.tree_sha.strip():
            raise ValueError("VERIFIED_TREE_REQUIRED")


@dataclass(frozen=True, slots=True)
class IntegrationResult:
    """The integration branch as it stands after the merge returned."""

    head_sha: str
    tree_sha: str
    blobs: dict[str, str | None] = field(default_factory=dict)
    merge_api_reported_success: bool = False


@dataclass(frozen=True, slots=True)
class MergeInspection:
    """The verdict, and enough detail to act on it without re-deriving it."""

    verdict: MergeVerdict
    reason: str
    #: Paths whose content differs from what was verified, with both ids.
    divergent_paths: tuple[tuple[str, str | None, str | None], ...] = ()
    #: Paths that were verified but for which the integration side recorded
    #: nothing. Unresolved evidence, not agreement.
    unresolved_paths: tuple[str, ...] = ()
    #: True only when every verified path holds the verified content.
    landed: bool = False
    #: True when the whole trees match, which is stronger than the invariant
    #: requires and makes a partial restore impossible by construction.
    identical_tree: bool = False

    @property
    def halts_lane(self) -> bool:
        """Whether this outcome must stop the merge lane."""
        return self.verdict is MergeVerdict.TREE_MISMATCH


def inspect_merge(
    verified: VerifiedResult,
    integration: IntegrationResult,
) -> MergeInspection:
    """Decide whether the integration branch holds what was verified.

    The order of these checks matters. A missing merge is reported before a
    mismatch, an incomplete record before a pass, and success is the last thing
    considered rather than the default.
    """

    identical_tree = (
        verified.tree_sha == integration.tree_sha
        and verified.tree_sha != UNKNOWN
        and integration.tree_sha != UNKNOWN
    )

    if not integration.merge_api_reported_success:
        return MergeInspection(
            verdict=MergeVerdict.MERGE_NOT_REPORTED,
            reason="MERGE_API_DID_NOT_REPORT_SUCCESS",
            identical_tree=identical_tree,
        )

    if not verified.blobs:
        # The API said yes and there is nothing to check it against. This is
        # exactly the position that let #706 through, so it is not a pass.
        return MergeInspection(
            verdict=MergeVerdict.EVIDENCE_INCOMPLETE,
            reason="NO_VERIFIED_PATHS_RECORDED",
            identical_tree=identical_tree,
        )

    divergent: list[tuple[str, str | None, str | None]] = []
    unresolved: list[str] = []
    for path, expected in sorted(verified.blobs.items()):
        if path not in integration.blobs:
            unresolved.append(path)
            continue
        found = integration.blobs[path]
        if expected == UNKNOWN or found == UNKNOWN:
            unresolved.append(path)
            continue
        if found != expected:
            divergent.append((path, expected, found))

    if divergent:
        return MergeInspection(
            verdict=MergeVerdict.TREE_MISMATCH,
            reason="INTEGRATION_TREE_DIFFERS_FROM_VERIFIED_RESULT",
            divergent_paths=tuple(divergent),
            unresolved_paths=tuple(unresolved),
            identical_tree=identical_tree,
        )

    if unresolved:
        return MergeInspection(
            verdict=MergeVerdict.EVIDENCE_INCOMPLETE,
            reason="VERIFIED_PATHS_NOT_RESOLVED_ON_INTEGRATION_BRANCH",
            unresolved_paths=tuple(unresolved),
            identical_tree=identical_tree,
        )

    return MergeInspection(
        verdict=MergeVerdict.LANDED,
        reason="INTEGRATION_HOLDS_THE_VERIFIED_RESULT",
        landed=True,
        identical_tree=identical_tree,
    )


def may_report_integrated(inspection: MergeInspection) -> bool:
    """Whether a session may record this merge as an integration.

    A single place to ask, so "the API returned success" can never be the
    answer. Every non-landed verdict is false, including the inconclusive ones.
    """
    return inspection.verdict is MergeVerdict.LANDED and inspection.landed


def restoration_paths(inspection: MergeInspection) -> tuple[str, ...]:
    """The paths to restore from the verified head after a mismatch.

    Returned in sorted order so a restoration is reproducible, and empty for
    any verdict that is not a mismatch -- there is nothing to restore when the
    merge did not happen or the evidence was never recorded.
    """
    if inspection.verdict is not MergeVerdict.TREE_MISMATCH:
        return ()
    return tuple(path for path, _, _ in inspection.divergent_paths)
