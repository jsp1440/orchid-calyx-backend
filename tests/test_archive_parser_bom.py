from __future__ import annotations

import pytest

from app.archive.parser import parse_structured


def test_parse_csv_with_bom():
    """CSV with leading UTF-8 BOM should be parsed correctly without BOM in keys."""
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
    """CSV without BOM should work as before."""
    content = "name,size\nA,1\n"
    result = parse_structured(content, ".csv")
    assert result == [{"name": "A", "size": "1"}]


def test_parse_json_without_bom():
    """JSON without BOM should work as before."""
    content = '{"a": 1}'
    result = parse_structured(content, ".json")
    assert result == {"a": 1}


def test_parse_yaml_without_bom():
    """YAML without BOM should work as before."""
    content = "a: 1\n"
    result = parse_structured(content, ".yaml")
    assert result == {"a": 1}


def test_unsupported_suffix_still_raises():
    """Unsupported suffixes should still raise ValueError."""
    with pytest.raises(ValueError, match="unsupported structured format"):
        parse_structured("\ufeffdata", ".txt")


def test_yml_extension_with_bom():
    """YAML with .yml extension and BOM should work."""
    content = "\ufeffkey: value\n"
    result = parse_structured(content, ".yml")
    assert result == {"key": "value"}
