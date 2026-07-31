from __future__ import annotations

import zipfile
from pathlib import Path

from app.archive.extractor import DocumentExtractor
from app.archive.fingerprint import sha256_bytes, sha256_file
from app.archive.parser import parse_structured
from app.archive.scanner import ArchiveScanner


def test_sha256_fingerprint_is_deterministic(tmp_path: Path):
    path = tmp_path / "a.txt"
    path.write_bytes(b"orchid continuum")
    assert sha256_file(path) == sha256_bytes(b"orchid continuum")
    assert len(sha256_file(path)) == 64


def test_recursive_scan_is_stable(tmp_path: Path):
    (tmp_path / "nested").mkdir()
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    (tmp_path / "nested" / "a.md").write_text("a", encoding="utf-8")
    paths = [item.relative_path for item in ArchiveScanner().scan(tmp_path)]
    assert paths == ["b.txt", "nested/a.md"]


def test_zip_extraction_blocks_path_traversal(tmp_path: Path):
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("../escape.txt", "no")
    try:
        ArchiveScanner().extract_zip(archive, tmp_path / "out")
    except ValueError as exc:
        assert "unsafe ZIP member" in str(exc)
    else:
        raise AssertionError("unsafe ZIP path was accepted")


def test_zip_extraction_and_registry_scan(tmp_path: Path):
    archive = tmp_path / "safe.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("folder/species.md", "# Species")
    destination = ArchiveScanner().extract_zip(archive, tmp_path / "out")
    files = list(ArchiveScanner().scan(destination))
    assert [item.relative_path for item in files] == ["folder/species.md"]


def test_markdown_html_and_structured_extraction(tmp_path: Path):
    markdown = tmp_path / "note.md"
    markdown.write_text("Orchid archive", encoding="utf-8")
    assert DocumentExtractor().extract(markdown).text == "Orchid archive"

    html = tmp_path / "page.html"
    html.write_text("<h1>Orchid</h1><p>Continuum</p>", encoding="utf-8")
    assert DocumentExtractor().extract(html).text == "Orchid\nContinuum"

    assert parse_structured('{"species": 3}', ".json") == {"species": 3}
    assert parse_structured("species,count\nCattleya,2\n", ".csv") == [
        {"species": "Cattleya", "count": "2"}
    ]


def test_image_extraction_exposes_ocr_hook(tmp_path: Path):
    image = tmp_path / "scan.jpg"
    image.write_bytes(b"not-a-real-image")
    result = DocumentExtractor().extract(image)
    assert result.extraction_method == "ocr_not_configured"
    assert result.text == ""
