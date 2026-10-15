from app.intake.html_links import (
    html_to_text_preserving_links,
    merge_plain_with_html_links,
)


def test_html_conversion_preserves_hidden_source_href():
    html = """
    <html><body>
      <h2>Research and Publications</h2>
      <p>Orchid pollination study High Priority</p>
      <p>Important evidence summary.</p>
      <a href="https://example.org/paper/123">View Source →</a>
    </body></html>
    """
    text = html_to_text_preserving_links(html)
    assert "Orchid pollination study High Priority" in text
    assert "https://example.org/paper/123" in text
    assert text.count("https://example.org/paper/123") == 1


def test_plain_text_keeps_preference_but_receives_html_only_source_links():
    plain = "Research and Publications\nOrchid evidence High Priority\nSummary only.\nView Source →"
    html = '<a href="https://example.org/source">View Source →</a>'
    merged = merge_plain_with_html_links(plain, html)
    assert merged.startswith(plain)
    assert "Source URL: https://example.org/source" in merged


def test_visible_url_is_not_duplicated():
    plain = "Source: https://example.org/source"
    html = '<a href="https://example.org/source">https://example.org/source</a>'
    merged = merge_plain_with_html_links(plain, html)
    assert merged == plain


def test_non_http_href_is_not_preserved():
    html = '<a href="mailto:person@example.org">Email</a><a href="javascript:alert(1)">Bad</a>'
    text = html_to_text_preserving_links(html)
    assert "mailto:" not in text
    assert "javascript:" not in text


def test_prefix_url_in_html_visible_text_is_not_dropped():
    """A shorter URL in HTML link should not be dropped if a longer URL is visible."""
    html = """
    <p>Supplement: https://example.org/paper/123/supplement</p>
    <a href="https://example.org/paper/123">View Source</a>
    """
    text = html_to_text_preserving_links(html)
    assert "Supplement: https://example.org/paper/123/supplement" in text
    assert "View Source" in text
    assert "Source URL: https://example.org/paper/123" in text


def test_prefix_url_in_plain_text_for_merge():
    """merge_plain_with_html_links should not drop a shorter URL if plain text has longer URL."""
    plain = "Full text: https://example.org/paper/1234"
    html = '<a href="https://example.org/paper/123">View Source</a>'
    merged = merge_plain_with_html_links(plain, html)
    assert merged.startswith(plain)
    assert "Source URL: https://example.org/paper/123" in merged


def test_url_followed_by_sentence_punctuation_counts_as_present():
    """A URL followed by . that ends text/line should not be added as Source URL."""
    plain = "Source: https://example.org/source."
    html = '<a href="https://example.org/source">View Source</a>'
    merged = merge_plain_with_html_links(plain, html)
    assert merged == plain
    assert "Source URL:" not in merged
