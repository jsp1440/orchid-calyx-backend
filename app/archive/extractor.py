from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import ClassVar, Protocol

from app.archive.parser import parse_structured


class OCRProvider(Protocol):
    def extract_text(self, path: Path) -> str: ...


class _HTMLText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        value = data.strip()
        if value:
            self.parts.append(value)


@dataclass(frozen=True)
class ExtractionResult:
    text: str
    structured_data: object | None = None
    extraction_method: str = "text"


class DocumentExtractor:
    TEXT_SUFFIXES: ClassVar[frozenset[str]] = frozenset({".txt", ".md", ".rst", ".log"})
    IMAGE_SUFFIXES: ClassVar[frozenset[str]] = frozenset(
        {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}
    )

    def __init__(self, ocr: OCRProvider | None = None) -> None:
        self.ocr = ocr

    def extract(self, path: Path) -> ExtractionResult:
        suffix = path.suffix.lower()
        if suffix in self.TEXT_SUFFIXES:
            return ExtractionResult(path.read_text(encoding="utf-8", errors="replace"))
        if suffix in {".csv", ".json", ".yaml", ".yml"}:
            raw = path.read_text(encoding="utf-8", errors="replace")
            return ExtractionResult(raw, parse_structured(raw, suffix), "structured")
        if suffix in {".html", ".htm"}:
            parser = _HTMLText()
            parser.feed(path.read_text(encoding="utf-8", errors="replace"))
            return ExtractionResult("\n".join(parser.parts), extraction_method="html")
        if suffix == ".pdf":
            from pypdf import PdfReader

            return ExtractionResult(
                "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages),
                extraction_method="pdf",
            )
        if suffix == ".docx":
            from docx import Document

            return ExtractionResult(
                "\n".join(paragraph.text for paragraph in Document(str(path)).paragraphs),
                extraction_method="docx",
            )
        if suffix in self.IMAGE_SUFFIXES:
            if self.ocr is None:
                return ExtractionResult("", extraction_method="ocr_not_configured")
            return ExtractionResult(self.ocr.extract_text(path), extraction_method="ocr")
        return ExtractionResult("", extraction_method="unsupported")
