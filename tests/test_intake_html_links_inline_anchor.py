"""Tests for merge_plain_with_html_links handling of inline anchor URLs."""

from app.intake.html_links import merge_plain_with_html_links


def test_inline_url_anchor_appends_missing_source_url():
    """Anchor with URL as visible text should append Source URL when not in plain text."""
    plain = "See the report."
    html = '<p>See <a href="https://a.org/x">https://a.org/x</a></p>'
    result = merge_plain_with_html_links(plain, html)
    assert result == "See the report.\n\nSource URL: https://a.org/x"


def test_non_inline_url_anchor_appends_as_before():
    """Anchor with different text should append Source URL as before (unchanged behavior)."""
    plain = "See the report."
    html = '<p>See <a href="https://a.org/x">the report</a></p>'
    result = merge_plain_with_html_links(plain, html)
    assert result == "See the report.\n\nSource URL: https://a.org/x"


def test_url_already_in_plain_text_not_duplicated():
    """URL already present in plain text should not be duplicated."""
    plain = "See https://a.org/x"
    html = '<a href="https://a.org/x">https://a.org/x</a>'
    result = merge_plain_with_html_links(plain, html)
    assert result == "See https://a.org/x"


def test_empty_plain_text_returns_html_conversion():
    """Empty plain text should return html_to_text_preserving_links result unchanged."""
    plain = ""
    html = '<a href="https://a.org/x">https://a.org/x</a>'
    result = merge_plain_with_html_links(plain, html)
    # When plain text is empty, the function returns html_to_text_preserving_links(html)
    # which includes the URL in the output
    assert "https://a.org/x" in result
    assert result.strip()  # Non-empty result
