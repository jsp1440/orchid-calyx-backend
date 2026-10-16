"""Tests for unmatched subject detection in compare_subjects."""
from runtime.matrix_relationship import (
    RelationshipAssertion,
    build_relationship_matrix,
    compare_subjects,
)


def assertion(subject: str, obj: str, state: str, confidence: float | None = None):
    return RelationshipAssertion(
        subject_id=subject,
        subject_label=subject.title(),
        dimension="pollinator",
        object_id=obj,
        object_label=obj.title(),
        state=state,
        confidence=confidence,
        provenance={"source": f"source-{subject}-{obj}-{state}"},
    )


def test_unmatched_subject_ids_when_right_subject_missing():
    """Test that a missing right_subject_id is reported in unmatched_subject_ids."""
    matrix = build_relationship_matrix(
        [
            assertion("taxon-a", "bee", "present"),
            assertion("taxon-b", "bee", "conflicting"),
        ],
        dimension="pollinator",
    )
    report = compare_subjects(matrix, "taxon-a", "taxon-zzz")
    assert report["unmatched_subject_ids"] == ["taxon-zzz"]


def test_unmatched_subject_ids_when_both_subjects_present():
    """Test that unmatched_subject_ids is empty when both subjects are in matrix."""
    matrix = build_relationship_matrix(
        [
            assertion("taxon-a", "bee", "present"),
            assertion("taxon-b", "bee", "conflicting"),
        ],
        dimension="pollinator",
    )
    report = compare_subjects(matrix, "taxon-a", "taxon-b")
    assert report["unmatched_subject_ids"] == []


def test_unmatched_subject_ids_both_missing():
    """Test that both missing subject ids are reported sorted."""
    matrix = build_relationship_matrix(
        [assertion("taxon-a", "bee", "present")],
        dimension="pollinator",
    )
    report = compare_subjects(matrix, "taxon-zzz", "taxon-yyy")
    assert report["unmatched_subject_ids"] == ["taxon-yyy", "taxon-zzz"]


def test_unmatched_subject_ids_left_subject_missing():
    """Test that a missing left_subject_id is reported in unmatched_subject_ids."""
    matrix = build_relationship_matrix(
        [
            assertion("taxon-a", "bee", "present"),
            assertion("taxon-b", "bee", "conflicting"),
        ],
        dimension="pollinator",
    )
    report = compare_subjects(matrix, "taxon-zzz", "taxon-a")
    assert report["unmatched_subject_ids"] == ["taxon-zzz"]


def test_unmatched_subject_ids_matrix_without_subjects_key():
    """Test that missing subjects key reports both ids sorted."""
    matrix = {"dimension": "pollinator", "objects": [], "cells": []}
    report = compare_subjects(matrix, "taxon-zzz", "taxon-aaa")
    assert report["unmatched_subject_ids"] == ["taxon-aaa", "taxon-zzz"]


def test_unmatched_subject_ids_unique_and_sorted():
    """Test that unmatched_subject_ids are unique and sorted."""
    matrix = build_relationship_matrix(
        [assertion("taxon-a", "bee", "present")],
        dimension="pollinator",
    )
    # Both subjects missing, should be sorted
    report = compare_subjects(matrix, "zebra", "alpha")
    assert report["unmatched_subject_ids"] == ["alpha", "zebra"]


def test_existing_keys_unchanged_when_unmatched_present():
    """Test that all existing keys remain unchanged when unmatched subjects are present."""
    matrix = build_relationship_matrix(
        [
            assertion("taxon-a", "bee", "present"),
            assertion("taxon-a", "moth", "absent"),
        ],
        dimension="pollinator",
    )
    report = compare_subjects(matrix, "taxon-a", "taxon-zzz")

    # Verify all existing keys are present
    assert "left_subject_id" in report
    assert "right_subject_id" in report
    assert "shared_present" in report
    assert "present_absent_disagreements" in report
    assert "comparisons" in report
    assert "read_only" in report

    # Verify values for existing keys are correct
    assert report["left_subject_id"] == "taxon-a"
    assert report["right_subject_id"] == "taxon-zzz"
    assert report["shared_present"] == 0
    assert report["present_absent_disagreements"] == 0
    assert len(report["comparisons"]) == 2
    assert report["read_only"] is True


def test_comparisons_contain_not_recorded_for_missing_subject():
    """Test that comparisons show not_recorded for missing subject."""
    matrix = build_relationship_matrix(
        [assertion("taxon-a", "bee", "present")],
        dimension="pollinator",
    )
    report = compare_subjects(matrix, "taxon-a", "taxon-zzz")

    assert len(report["comparisons"]) == 1
    comparison = report["comparisons"][0]
    assert comparison["left_state"] == "present"
    assert comparison["right_state"] == "not_recorded"
    assert comparison["same_state"] is False
