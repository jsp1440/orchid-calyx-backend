"""Tests for executive summary pluralization of verbs based on counts."""
from runtime.executive.summarizer import executive_summary


def test_singular_verbs_for_count_one():
    """Test that singular verbs are used when counts are exactly 1."""
    state = {
        "subsystems": [
            {"id": "a", "name": "A", "status": "healthy"},
            {"id": "b", "name": "B", "status": "blocked", "owner_required": True},
        ],
        "priorities": [],
        "generated_at": "2024-01-01",
        "recommendations": [],
        "changes": [],
    }
    result = executive_summary(state)
    assert result["executive_summary"] == (
        "1/2 executive subsystems are healthy. 1 has blockers and 1 needs owner attention."
    )


def test_plural_verbs_for_multiple_counts():
    """Test that plural verbs are used when counts are greater than 1."""
    state = {
        "subsystems": [
            {"id": "a", "name": "A", "status": "blocked"},
            {"id": "b", "name": "B", "status": "blocked"},
            {"id": "c", "name": "C", "status": "blocked", "owner_required": True},
        ],
        "priorities": [],
        "generated_at": "2024-01-01",
        "recommendations": [],
        "changes": [],
    }
    result = executive_summary(state)
    assert result["executive_summary"] == (
        "0/3 executive subsystems are healthy. 3 have blockers and 1 needs owner attention."
    )


def test_plural_verbs_for_two_owner_required():
    """Test plural verb for owner_required count of 2."""
    state = {
        "subsystems": [
            {"id": "a", "name": "A", "status": "blocked"},
            {"id": "b", "name": "B", "status": "blocked", "owner_required": True},
            {"id": "c", "name": "C", "status": "blocked", "owner_required": True},
        ],
        "priorities": [],
        "generated_at": "2024-01-01",
        "recommendations": [],
        "changes": [],
    }
    result = executive_summary(state)
    assert result["executive_summary"] == (
        "0/3 executive subsystems are healthy. 3 have blockers and 2 need owner attention."
    )


def test_zero_counts_use_plural_verbs():
    """Test that zero counts use plural verbs."""
    state = {
        "subsystems": [],
        "priorities": [],
        "generated_at": "2024-01-01",
        "recommendations": [],
        "changes": [],
    }
    result = executive_summary(state)
    assert result["executive_summary"] == (
        "0/0 executive subsystems are healthy. 0 have blockers and 0 need owner attention."
    )
