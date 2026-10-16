from __future__ import annotations

from pathlib import Path

from app.archive.extractor import DocumentExtractor


def test_skip_style_content(tmp_path: Path):
    """Test that CSS inside <style> tags is skipped."""
    html = tmp_path / "style.html"
    html.write_text(
        "<html><head><title>Notes</title><style>body{color:red}</style></head><body><p>Hello</p></body></html>",
        encoding="utf-8",
    )
    result = DocumentExtractor().extract(html)
    assert result.text == "Notes\nHello"
    assert result.extraction_method == "html"


def test_skip_script_content(tmp_path: Path):
    """Test that JavaScript inside <script> tags is skipped."""
    html = tmp_path / "script.html"
    html.write_text(
        "<p>A</p><script>if (a < b) { x(); }</script><p>B</p>",
        encoding="utf-8",
    )
    result = DocumentExtractor().extract(html)
    assert result.text == "A\nB"
    assert result.extraction_method == "html"


def test_normal_html_unchanged(tmp_path: Path):
    """Test that normal HTML extraction remains unchanged."""
    html = tmp_path / "normal.html"
    html.write_text(
        "<h1>Orchid</h1><p>Continuum</p>",
        encoding="utf-8",
    )
    result = DocumentExtractor().extract(html)
    assert result.text == "Orchid\nContinuum"
    assert result.extraction_method == "html"
