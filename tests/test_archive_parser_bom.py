from __future__ import annotations

import pytest

from app.archive.parser import parse_structured


def test_parse_csv_with_bom():
    """CSV with leading UTF-8 BOM should be parsed correctly."""
    content = "\ufeffname,size\nA,1\n"
    result = parse_structured(content, ".csv")
    assert result == [{"name": "A", "size": "1"}]


def test_parse_json_with_bom():
    """JSON with leading UTF-8 BOM should be parsed correctly."""
    content = '\ufeff{"a": 1}'
    result = parse_structured(content, ".json")
    assert result == {"a": 1}


def test_parse_yaml_with_bom():
    """YAML with leading UTF-8 BOM should be parsed correctly."""
    content = "\ufeffa: 1\n"
    result = parse_structured(content, ".yaml")
    assert result == {"a": 1}


def test_parse_csv_without_bom():
    """CSV without BOM should still work correctly."""
    content = "name,size\nA,1\n"
    result = parse_structured(content, ".csv")
    assert result == [{"name": "A", "size": "1"}]


def test_parse_json_without_bom():
    """JSON without BOM should still work correctly."""
    content = '{"a": 1}'
    result = parse_structured(content, ".json")
    assert result == {"a": 1}


def test_parse_yaml_without_bom():
    """YAML without BOM should still work correctly."""
    content = "a: 1\n"
    result = parse_structured(content, ".yaml")
    assert result == {"a": 1}


def test_parse_unsupported_format_raises_error():
    """Unsupported formats should raise ValueError regardless of BOM."""
    with pytest.raises(ValueError, match="unsupported structured format"):
        parse_structured(".txt", ".txt")

    with pytest.raises(ValueError, match="unsupported structured format"):
        parse_structured("\ufeff.txt", ".txt")
