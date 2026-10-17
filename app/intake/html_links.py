"""Pure HTML text/link preservation helpers for intelligence intake.

This module has no mailbox, network, credential, or persistence capabilities.
It exists so HTML briefing links survive conversion into the plain text consumed
by the deterministic intelligence parser.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urlparse


def _is_link_present(link: str, text: str) -> bool:
    """Check if link is present in text with proper word boundary/delimiter handling.

    A link counts as present only when some occurrence of it in the text is
    immediately followed by: end of text; whitespace; one of `, ; : ! ? ) ] > " '`;
    or a `.` that is itself followed by end of text or whitespace.
    """
    # Escape special regex characters in the link
    escaped_link = re.escape(link)
    # Match the link followed by either:
    # - end of string ($)
    # - whitespace (\s)
    # - specific punctuation chars
    # - a period followed by whitespace or end of string
    pattern = (
        escaped_link
        + r"(?="
        + r"$"  # end of text
        + r"|"
        + r"\s"  # whitespace
        + r"|"
        + r"[,;:!?\)\]>\"']"  # specific punctuation
        + r"|"
        + r"\.(?=\s|$)"  # period followed by whitespace or end
        + r")"
    )
    return bool(re.search(pattern, text))


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
        missing_links = [link for link in self.links if not _is_link_present(link, text)]
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

    # Extract links that appear in the "Source URL: " lines from html_text
    html_links_from_source_lines = [
        line.removeprefix("Source URL: ").strip()
        for line in html_text.splitlines()
        if line.startswith("Source URL: ")
    ]

    # Also extract all href links directly from the HTML (including inline URLs)
    parser = _LinkPreservingParser()
    parser.feed(html or "")
    parser.close()
    all_html_links = parser.links

    # Combine both sources and deduplicate
    all_links = list(dict.fromkeys(html_links_from_source_lines + all_html_links))

    # Find links that are not present in the plain text
    missing = [link for link in all_links if link and not _is_link_present(link, plain)]
    if not missing:
        return plain
    return plain + "\n\n" + "\n".join(f"Source URL: {link}" for link in missing)
