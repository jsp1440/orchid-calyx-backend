"""Tests for _parse_points_breakdown helper function.

Tests cover the requirement that _parse_points_breakdown returns None for
non-dict JSON values and other edge cases.
"""

from app.routers.judging import _parse_points_breakdown


class TestParsePointsBreakdown:
    """Test _parse_points_breakdown behavior."""

    def test_none_input(self):
        """None input should return None."""
        assert _parse_points_breakdown(None) is None

    def test_empty_string(self):
        """Empty string should return None."""
        assert _parse_points_breakdown("") is None

    def test_invalid_json(self):
        """Invalid JSON should return None."""
        assert _parse_points_breakdown("not json") is None

    def test_json_array(self):
        """JSON array should return None."""
        assert _parse_points_breakdown("[1, 2]") is None

    def test_json_string(self):
        """JSON string should return None."""
        assert _parse_points_breakdown('"x"') is None

    def test_json_number(self):
        """JSON number should return None."""
        assert _parse_points_breakdown("5") is None

    def test_valid_dict(self):
        """Valid JSON dict should return the dict."""
        result = _parse_points_breakdown('{"a": 1}')
        assert result == {"a": 1}

    def test_empty_dict(self):
        """Empty JSON dict should return empty dict."""
        result = _parse_points_breakdown('{}')
        assert result == {}

    def test_nested_dict(self):
        """Nested JSON dict should return the dict."""
        result = _parse_points_breakdown('{"a": {"b": 2}}')
        assert result == {"a": {"b": 2}}

    def test_dict_with_various_types(self):
        """Dict with various value types should return the dict."""
        result = _parse_points_breakdown('{"str": "value", "num": 42, "bool": true, "null": null}')
        assert result == {"str": "value", "num": 42, "bool": True, "null": None}
