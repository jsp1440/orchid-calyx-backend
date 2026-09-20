"""The #706 failure mode, and the invariant that catches it.

On 2026-09-19 a pull request passed five rounds of independent review at
`4efa379`, was merged with `expectedHeadSha` naming that commit, and the GitHub
merge API returned success. The squash produced the tree of `16cb85d`. Six
regressions reached the integration branch, one of them a locality leak, and
nothing noticed for twenty minutes because the merge had said yes.

These tests pin the invariant that makes that impossible to repeat. The object
ids below are the real ones from the incident.
"""

from __future__ import annotations

import pytest

from app.calyx_orchestrator.merge_integrity import (
    UNKNOWN,
    IntegrationResult,
    MergeVerdict,
    VerifiedResult,
    inspect_merge,
    may_report_integrated,
    restoration_paths,
)

#: Real object ids from the incident.
VERIFIED_HEAD = "4efa3794300f005a5bfcb25f30fa9dc2ff9551b7"
VERIFIED_TREE = "f42cf58d410d21e4ebf38b1bdb149a8db5cf08c0"
BAD_SQUASH_HEAD = "73f634c9e107653ef9859f5c909a5d5faeba3891"
BAD_SQUASH_TREE = "315407fa25c0e14a283d5c058cefcfad753f6ea7"

TOUCHED = (
    "src/lib/cognitiveIntegration.ts",
    "src/lib/coordinateShapes.test.ts",
    "src/components/calyx/ReasoningMapPanel.tsx",
    "src/components/calyx/ReasoningMapPanel.locality.test.tsx",
)


def verified(**blobs: str | None) -> VerifiedResult:
    return VerifiedResult(
        head_sha=VERIFIED_HEAD,
        tree_sha=VERIFIED_TREE,
        blobs=blobs or {path: f"verified-{path}" for path in TOUCHED},
    )


def landed_cleanly() -> IntegrationResult:
    return IntegrationResult(
        head_sha="60eb2006889c583f83e2c9de4dc39413d3a2dd31",
        tree_sha=VERIFIED_TREE,
        blobs={path: f"verified-{path}" for path in TOUCHED},
        merge_api_reported_success=True,
    )


class TestTheIncident:
    def test_a_squash_that_drops_verified_commits_is_caught(self):
        """The #706 failure: API success, wrong tree."""
        # Every touched path holds the earlier content.
        dropped = IntegrationResult(
            head_sha=BAD_SQUASH_HEAD,
            tree_sha=BAD_SQUASH_TREE,
            blobs={path: f"stale-{path}" for path in TOUCHED},
            merge_api_reported_success=True,
        )
        result = inspect_merge(verified(), dropped)

        assert result.verdict is MergeVerdict.TREE_MISMATCH
        assert result.landed is False
        assert result.halts_lane is True
        assert may_report_integrated(result) is False
        assert len(result.divergent_paths) == len(TOUCHED)

    def test_the_lane_stops_and_names_what_to_restore(self):
        dropped = IntegrationResult(
            head_sha=BAD_SQUASH_HEAD,
            tree_sha=BAD_SQUASH_TREE,
            blobs={path: f"stale-{path}" for path in TOUCHED},
            merge_api_reported_success=True,
        )
        result = inspect_merge(verified(), dropped)
        # Sorted, so a restoration is reproducible rather than incidental.
        assert restoration_paths(result) == tuple(sorted(TOUCHED))

    def test_one_dropped_file_is_enough(self):
        """A partial drop is the dangerous shape: most of it looks right."""
        blobs = {path: f"verified-{path}" for path in TOUCHED}
        blobs["src/lib/cognitiveIntegration.ts"] = "stale-the-one-that-matters"
        partial = IntegrationResult(
            head_sha=BAD_SQUASH_HEAD,
            tree_sha=BAD_SQUASH_TREE,
            blobs=blobs,
            merge_api_reported_success=True,
        )
        result = inspect_merge(verified(), partial)

        assert result.verdict is MergeVerdict.TREE_MISMATCH
        assert result.divergent_paths == (
            (
                "src/lib/cognitiveIntegration.ts",
                "verified-src/lib/cognitiveIntegration.ts",
                "stale-the-one-that-matters",
            ),
        )


class TestApiSuccessIsNotEvidence:
    def test_success_with_no_recorded_paths_is_not_a_pass(self):
        """The position that let #706 through."""
        result = inspect_merge(
            VerifiedResult(head_sha=VERIFIED_HEAD, tree_sha=VERIFIED_TREE),
            landed_cleanly(),
        )
        assert result.verdict is MergeVerdict.EVIDENCE_INCOMPLETE
        # The reason too: `all([])` is vacuously true, so without this gate the
        # deletions-only check absorbs an empty record and reports a reason that
        # is not what happened.
        assert result.reason == "NO_VERIFIED_PATHS_RECORDED"
        assert may_report_integrated(result) is False

    def test_a_path_the_integration_side_never_resolved_is_not_agreement(self):
        thin = IntegrationResult(
            head_sha="abc",
            tree_sha=VERIFIED_TREE,
            blobs={TOUCHED[0]: f"verified-{TOUCHED[0]}"},
            merge_api_reported_success=True,
        )
        result = inspect_merge(verified(), thin)
        assert result.verdict is MergeVerdict.EVIDENCE_INCOMPLETE
        assert set(result.unresolved_paths) == set(TOUCHED[1:])
        assert may_report_integrated(result) is False

    def test_an_unresolved_blob_id_is_never_a_wildcard(self):
        blobs = {path: f"verified-{path}" for path in TOUCHED}
        blobs[TOUCHED[0]] = ""
        result = inspect_merge(
            verified(),
            IntegrationResult(
                head_sha="abc",
                tree_sha=VERIFIED_TREE,
                blobs=blobs,
                merge_api_reported_success=True,
            ),
        )
        assert result.verdict is MergeVerdict.EVIDENCE_INCOMPLETE
        assert may_report_integrated(result) is False

    def test_no_merge_reported_is_not_inspected_as_a_mismatch(self):
        result = inspect_merge(
            verified(),
            IntegrationResult(
                head_sha=BAD_SQUASH_HEAD,
                tree_sha=BAD_SQUASH_TREE,
                blobs={path: f"stale-{path}" for path in TOUCHED},
                merge_api_reported_success=False,
            ),
        )
        assert result.verdict is MergeVerdict.MERGE_NOT_REPORTED
        assert result.halts_lane is False
        assert may_report_integrated(result) is False
        assert restoration_paths(result) == ()


class TestTheGoodCase:
    def test_the_verified_result_landing_is_reported_as_landed(self):
        result = inspect_merge(verified(), landed_cleanly())
        assert result.verdict is MergeVerdict.LANDED
        assert result.landed is True
        assert may_report_integrated(result) is True
        assert result.halts_lane is False
        assert restoration_paths(result) == ()

    def test_identical_trees_are_noted_as_the_stronger_proof(self):
        """What the restoration of #706 actually had: same tree object."""
        result = inspect_merge(verified(), landed_cleanly())
        assert result.identical_tree is True

    def test_landing_onto_a_branch_carrying_other_work_still_passes(self):
        """The general case: the tree differs, the touched paths do not.

        Whole-tree equality only held for #706 because the branch had merged
        its base in. Requiring it in general would fail every honest merge.
        """
        result = inspect_merge(
            verified(),
            IntegrationResult(
                head_sha="deadbee",
                tree_sha="a-different-tree-carrying-other-peoples-work",
                blobs={path: f"verified-{path}" for path in TOUCHED},
                merge_api_reported_success=True,
            ),
        )
        assert result.verdict is MergeVerdict.LANDED
        assert result.identical_tree is False
        assert may_report_integrated(result) is True

    def test_a_record_of_only_deletions_is_never_a_pass(self):
        """The fifth instance of one failure class, and the last one.

        Rounds 1-4 each narrowed where a deletion's evidence could come from --
        the path must exist at the verified head, then at a caller-named ref,
        then at the merge base -- and each time a record made only of deletions
        still returned LANDED after reading none of the integration side's
        content. Absence is symmetric: two lineages that both lack a file agree
        about it for reasons that have nothing to do with this merge.
        """
        result = inspect_merge(
            verified(**{"src/lib/dead.ts": None}),
            IntegrationResult(
                head_sha="abc",
                tree_sha="a-different-tree",
                blobs={"src/lib/dead.ts": None},
                merge_api_reported_success=True,
            ),
        )

        assert result.verdict is MergeVerdict.EVIDENCE_INCOMPLETE
        assert result.reason == "ONLY_DELETIONS_RECORDED_SO_NOTHING_WAS_COMPARED"
        assert may_report_integrated(result) is False

    def test_a_deletion_beside_surviving_content_is_agreement(self):
        result = inspect_merge(
            verified(**{"src/lib/dead.ts": None, "src/lib/kept.ts": "blob-kept"}),
            IntegrationResult(
                head_sha="abc",
                tree_sha=VERIFIED_TREE,
                blobs={"src/lib/dead.ts": None, "src/lib/kept.ts": "blob-kept"},
                merge_api_reported_success=True,
            ),
        )

        assert result.verdict is MergeVerdict.LANDED
        assert may_report_integrated(result) is True

    def test_a_deletion_the_merge_did_not_apply_is_still_a_mismatch(self):
        result = inspect_merge(
            verified(**{"src/lib/dead.ts": None, "src/lib/kept.ts": "blob-kept"}),
            IntegrationResult(
                head_sha="abc",
                tree_sha=VERIFIED_TREE,
                blobs={"src/lib/dead.ts": "still-here", "src/lib/kept.ts": "blob-kept"},
                merge_api_reported_success=True,
            ),
        )

        assert result.verdict is MergeVerdict.TREE_MISMATCH
        assert result.divergent_paths == (("src/lib/dead.ts", None, "still-here"),)

    @pytest.mark.parametrize("head,tree", [("", "t"), ("h", ""), ("  ", "t")])
    def test_a_verified_result_without_identity_is_refused(self, head, tree):
        with pytest.raises(ValueError):
            VerifiedResult(head_sha=head, tree_sha=tree)



class TestWhyTheIdenticalTreeGuardsCannotBeExercised:
    """`identical_tree`'s two `!= UNKNOWN` conjuncts are unreachable, and this
    says so rather than asserting coverage that does not exist.

    An attempt to pin them failed on its own premise: UNKNOWN is the empty
    string, `VerifiedResult` refuses an empty `tree_sha` in `__post_init__`, and
    identity needs BOTH sides equal -- so no input reaching `inspect_merge` can
    make the guarded comparison true. (The attempt used `"?"` as a stand-in for
    UNKNOWN, which is not UNKNOWN, and the test was red before any mutant ran.)

    The conjuncts stay: they are correct, they are free, and `identical_tree` is
    reported to a reader as the stronger proof. But they are a survivor, and the
    survivor list names them.
    """

    def test_the_verified_side_can_never_carry_an_unresolved_tree(self):
        with pytest.raises(ValueError):
            VerifiedResult(head_sha=VERIFIED_HEAD, tree_sha=UNKNOWN)

    def test_so_an_unresolved_integration_tree_is_never_identical_either(self):
        result = inspect_merge(
            verified(**{TOUCHED[0]: "blob"}),
            IntegrationResult(head_sha="abc", tree_sha=UNKNOWN, blobs={TOUCHED[0]: "blob"},
                              merge_api_reported_success=True),
        )
        assert result.verdict is MergeVerdict.LANDED
        assert result.identical_tree is False
