"""Pure HTML text/link preservation helpers for intelligence intake.

This module has no mailbox, network, credential, or persistence capabilities.
It exists so HTML briefing links survive conversion into the plain text consumed
by the deterministic intelligence parser.
"""

from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urlparse


class _LinkPreservingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.links: list[str] = []

    @staticmethod
    def _allowed_href(value: str) -> bool:
        try:
            parsed = urlparse(value.strip())
        except ValueError:
            return False
        return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = next((value for name, value in attrs if name.lower() == "href"), None)
        if href and self._allowed_href(href):
            normalized = href.strip()
            if normalized not in self.links:
                self.links.append(normalized)

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if text:
            self.parts.append(text)

    def text(self) -> str:
        text = "\n".join(self.parts).strip()
        missing_links = [link for link in self.links if link not in text]
        if not missing_links:
            return text
        source_block = "\n".join(f"Source URL: {link}" for link in missing_links)
        return f"{text}\n{source_block}".strip() if text else source_block


def html_to_text_preserving_links(html: str) -> str:
    """Convert HTML to readable text while preserving unique HTTP(S) hrefs."""
    parser = _LinkPreservingParser()
    parser.feed(html or "")
    parser.close()
    return parser.text()


def merge_plain_with_html_links(plain_text: str, html: str) -> str:
    """Prefer plain text but append source URLs present only in HTML anchors."""
    plain = (plain_text or "").strip()
    html_text = html_to_text_preserving_links(html)
    if not plain:
        return html_text

    html_links = [
        line.removeprefix("Source URL: ").strip()
        for line in html_text.splitlines()
        if line.startswith("Source URL: ")
    ]
    missing = [link for link in html_links if link and link not in plain]
    if not missing:
        return plain
    return plain + "\n\n" + "\n".join(f"Source URL: {link}" for link in missing)
