import io
import zipfile

import pytest

from app.intake.universal import classify, extract_safe_text, inspect_zip, validate_file
from app.intake.routes import router
from app.storage import LocalImmutableStorage, sanitize_filename


def test_original_is_content_addressed_and_immutable(tmp_path):
    storage = LocalImmutableStorage(tmp_path)
    first = storage.preserve(b"orchid evidence", "../unsafe report.txt")
    second = storage.preserve(b"orchid evidence", "renamed.txt")
    assert first.storage_key == second.storage_key
    assert storage.read(first.storage_key) == b"orchid evidence"
    assert first.display_filename == "unsafe report.txt"


def test_filename_traversal_is_removed():
    assert sanitize_filename("../../evil<script>.txt") == "evil_script_.txt"


def test_oversized_and_unsupported_files_fail_stably():
    with pytest.raises(ValueError, match="FILE_TOO_LARGE"):
        validate_file("report.txt", b"1234", max_bytes=3)
    with pytest.raises(ValueError, match="UNSUPPORTED_FILE_TYPE"):
        validate_file("payload.exe", b"MZ")


def test_zip_traversal_and_bomb_limits_are_blocked():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("../escape.txt", "bad")
    with pytest.raises(ValueError, match="ZIP_PATH_TRAVERSAL"):
        inspect_zip(stream.getvalue())
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("safe.txt", "x" * 20)
    with pytest.raises(ValueError, match="UNSAFE_ARCHIVE_LIMIT"):
        inspect_zip(stream.getvalue(), max_expanded_bytes=10)


def test_grant_is_candidate_with_unreviewed_progress_and_no_external_contact():
    text = "MBZ Species Conservation Fund grant application. Amount requested. Deadline July 30, 2026. https://api.example.test/data Orchid Continuum species dossier."
    result = classify("mbz-application.txt", text)
    assert result.document_type == "grant application"
    assert result.grant_candidate["verification_state"] == "UNREVIEWED"
    assert result.external_sources[0]["contacted"] is False
    assert result.candidate_dates[0]["date_type"] == "date mentioned in text"


def test_low_signal_file_is_reviewed_not_deleted():
    result = classify("contract.txt", "Professional services agreement and budget")
    assert result.relevance == "uncertain"
    assert "human review required" in result.explanation


def test_safe_text_extraction_does_not_execute_or_render_html():
    text, status = extract_safe_text(".txt", b"<script>alert(1)</script>")
    assert status == "EXTRACTED"
    assert text == "<script>alert(1)</script>"


def test_static_batch_routes_precede_legacy_source_detail_and_text_remains_registered():
    paths = [route.path for route in router.routes]
    assert "/api/intake/text" in paths
    assert paths.index("/api/intake/batches") < paths.index("/api/intake/{source_id}")
