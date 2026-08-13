from app.intake.html_links import html_to_text_preserving_links, merge_plain_with_html_links


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
