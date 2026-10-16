"""Tests for generate_recommendations limit parameter behavior."""
from runtime.executive.recommendations import generate_recommendations


def test_limit_zero_returns_empty_list():
    """limit=0 should return an empty list."""
    priorities = [
        {"subsystem_id": "a", "score": 70, "priority": "high"},
        {"subsystem_id": "b", "score": 50, "priority": "medium"},
    ]
    subsystems = [
        {"id": "a", "name": "A"},
        {"id": "b", "name": "B"},
    ]
    recommendations = generate_recommendations(priorities, subsystems, limit=0)
    assert recommendations == []


def test_limit_negative_returns_empty_list():
    """limit=-1 should return an empty list."""
    priorities = [
        {"subsystem_id": "a", "score": 70, "priority": "high"},
        {"subsystem_id": "b", "score": 50, "priority": "medium"},
    ]
    subsystems = [
        {"id": "a", "name": "A"},
        {"id": "b", "name": "B"},
    ]
    recommendations = generate_recommendations(priorities, subsystems, limit=-1)
    assert recommendations == []


def test_limit_one_returns_single_recommendation():
    """limit=1 should return exactly one recommendation."""
    priorities = [
        {"subsystem_id": "a", "score": 70, "priority": "high"},
        {"subsystem_id": "b", "score": 50, "priority": "medium"},
    ]
    subsystems = [
        {"id": "a", "name": "A"},
        {"id": "b", "name": "B"},
    ]
    recommendations = generate_recommendations(priorities, subsystems, limit=1)
    assert len(recommendations) == 1
    assert recommendations[0]["id"] == "exec-a"
    assert recommendations[0]["priority"] == "high"
    assert recommendations[0]["score"] == 70
