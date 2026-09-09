"""Regression contract for opaque immediate Claude provider failures."""

from pathlib import Path

LANE = Path(".github/workflows/orchid-completion-lane.yml")


def test_opaque_zero_usage_claude_error_routes_to_authorized_fallback():
    text = LANE.read_text()
    classifier = text[
        text.index("name: Classify Claude terminal state")
        : text.index("name: Execute bounded Gemini fallback")
    ]

    assert '.is_error // false' in classifier
    assert '.num_turns // ""' in classifier
    assert '(.modelUsage // {}) | length' in classifier
    assert '"$is_error" == "true"' in classifier
    assert '"$subtype" == "success"' in classifier
    assert '"$num_turns" -le 1' in classifier
    assert '"$model_usage_count" == "0"' in classifier
    assert "kind=safe_provider" in classifier
    assert "fallback=true" in classifier


def test_security_classification_precedes_opaque_fallback():
    text = LANE.read_text()
    classifier = text[
        text.index("name: Classify Claude terminal state")
        : text.index("name: Execute bounded Gemini fallback")
    ]

    security = classifier.index('kind=security')
    opaque = classifier.index('"$is_error" == "true"')
    assert security < opaque
