"""Tests for handling various author shapes in literature paper summaries.

Tests that `LiteratureResultRepository.summarize` properly handles authors
when they are strings, lists, or other types.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.literature_extraction.repository import LiteratureResultRepository


def write_paper(root: Path, paper_id: str, authors: object) -> None:
    """Write a minimal paper.json with the given authors value."""
    directory = root / paper_id
    directory.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": "1.0.0",
        "paper_id": paper_id,
        "metadata": {
            "title": "Test Paper",
            "authors": authors,
        },
    }
    (directory / "paper.json").write_text(json.dumps(record), encoding="utf-8")


def test_string_authors_become_single_element_tuple(tmp_path: Path):
    """A string authors value is wrapped as a one-element tuple."""
    write_paper(tmp_path, "p1", "Dressler, R.L.")
    summary = LiteratureResultRepository(tmp_path).summarize("p1")
    assert summary["authors"] == ("Dressler, R.L.",)


def test_blank_string_authors_become_empty_tuple(tmp_path: Path):
    """A blank string authors value becomes an empty tuple."""
    write_paper(tmp_path, "p1", "   ")
    summary = LiteratureResultRepository(tmp_path).summarize("p1")
    assert summary["authors"] == ()


def test_empty_string_authors_become_empty_tuple(tmp_path: Path):
    """An empty string authors value becomes an empty tuple."""
    write_paper(tmp_path, "p1", "")
    summary = LiteratureResultRepository(tmp_path).summarize("p1")
    assert summary["authors"] == ()


def test_list_authors_keep_current_behavior(tmp_path: Path):
    """A list of authors is processed as before."""
    write_paper(tmp_path, "p1", ["Ríos, M.", "Tan, L."])
    summary = LiteratureResultRepository(tmp_path).summarize("p1")
    assert summary["authors"] == ("Ríos, M.", "Tan, L.")


def test_authors_list_is_bounded_to_ten(tmp_path: Path):
    """A list with many authors is bounded to 10 elements."""
    many_authors = [f"Author {i}" for i in range(40)]
    write_paper(tmp_path, "p1", many_authors)
    summary = LiteratureResultRepository(tmp_path).summarize("p1")
    assert len(summary["authors"]) == 10
    assert summary["authors"] == tuple(f"Author {i}" for i in range(10))


def test_number_authors_become_empty_tuple(tmp_path: Path):
    """A number in the authors field becomes an empty tuple."""
    write_paper(tmp_path, "p1", 42)
    summary = LiteratureResultRepository(tmp_path).summarize("p1")
    assert summary["authors"] == ()


def test_dict_authors_become_empty_tuple(tmp_path: Path):
    """A dict in the authors field becomes an empty tuple."""
    write_paper(tmp_path, "p1", {"a": 1})
    summary = LiteratureResultRepository(tmp_path).summarize("p1")
    assert summary["authors"] == ()


def test_null_authors_become_empty_tuple(tmp_path: Path):
    """A null/None authors value becomes an empty tuple."""
    write_paper(tmp_path, "p1", None)
    summary = LiteratureResultRepository(tmp_path).summarize("p1")
    assert summary["authors"] == ()


def test_missing_authors_become_empty_tuple(tmp_path: Path):
    """A missing authors field becomes an empty tuple."""
    directory = tmp_path / "p1"
    directory.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": "1.0.0",
        "paper_id": "p1",
        "metadata": {
            "title": "Test Paper",
        },
    }
    (directory / "paper.json").write_text(json.dumps(record), encoding="utf-8")
    summary = LiteratureResultRepository(tmp_path).summarize("p1")
    assert summary["authors"] == ()


def test_string_authors_with_whitespace_are_stripped(tmp_path: Path):
    """A string authors value with leading/trailing whitespace is stripped."""
    write_paper(tmp_path, "p1", "  Dressler, R.L.  ")
    summary = LiteratureResultRepository(tmp_path).summarize("p1")
    assert summary["authors"] == ("Dressler, R.L.",)


def test_list_with_string_elements_are_converted_to_strings(tmp_path: Path):
    """List elements are converted to strings via str()."""
    write_paper(tmp_path, "p1", ["Author One", "Author Two"])
    summary = LiteratureResultRepository(tmp_path).summarize("p1")
    assert summary["authors"] == ("Author One", "Author Two")


def test_summary_author_shapes_in_as_dict(tmp_path: Path):
    """The as_dict() method properly serializes authors tuples."""
    write_paper(tmp_path, "p1", "Single Author")
    summary = LiteratureResultRepository(tmp_path).summarize("p1")
    payload = summary.as_dict()
    # as_dict converts the tuple to a list for JSON serialization
    assert payload["authors"] == ["Single Author"]
    assert isinstance(payload["authors"], list)
