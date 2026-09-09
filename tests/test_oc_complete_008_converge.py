"""Tests for OC-COMPLETE-008 CONVERGE items.

Covers:
- shows.py router registered in main.py (was unreachable): verified via static
  analysis of main.py — SQLAlchemy not installed in test environment
- volunteer_ops.py router registered in main.py (was unreachable): same
- Path traversal fix in app/storage.py
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app import storage as _storage_module
from app.storage import _confine_to_storage, file_exists, read_file

_MAIN_PY = Path(__file__).parent.parent / "app" / "main.py"
_MAIN_SRC = _MAIN_PY.read_text()


# ---------------------------------------------------------------------------
# Router registration — shows.py (static analysis; SQLAlchemy not in test env)
# ---------------------------------------------------------------------------


class TestShowsRouterRegistered:
    def test_shows_imported_in_main(self):
        assert re.search(r"\bshows\b", _MAIN_SRC), "shows not imported in main.py"

    def test_shows_router_included(self):
        assert "shows.router" in _MAIN_SRC, "shows.router not included in main.py"

    def test_shows_in_from_routers_block(self):
        m = re.search(r"from app\.routers import \((.+?)\)", _MAIN_SRC, re.DOTALL)
        assert m, "could not find 'from app.routers import (...)' block"
        assert "shows" in m.group(1)


# ---------------------------------------------------------------------------
# Router registration — volunteer_ops.py (static analysis)
# ---------------------------------------------------------------------------


class TestVolunteerOpsRouterRegistered:
    def test_volunteer_ops_imported_in_main(self):
        assert re.search(r"\bvolunteer_ops\b", _MAIN_SRC), "volunteer_ops not imported in main.py"

    def test_volunteer_ops_router_included(self):
        assert "volunteer_ops.router" in _MAIN_SRC, "volunteer_ops.router not included in main.py"

    def test_volunteer_ops_in_from_routers_block(self):
        m = re.search(r"from app\.routers import \((.+?)\)", _MAIN_SRC, re.DOTALL)
        assert m, "could not find 'from app.routers import (...)' block"
        assert "volunteer_ops" in m.group(1)


# ---------------------------------------------------------------------------
# Path traversal fix in storage.py
# ---------------------------------------------------------------------------


class TestStoragePathConfinement:
    """_confine_to_storage must block paths outside STORAGE_DIR."""

    @pytest.fixture(autouse=True)
    def use_tmp_storage(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_storage_module, "STORAGE_DIR", tmp_path)
        return tmp_path

    def test_file_inside_storage_allowed(self, tmp_path):
        target = tmp_path / "abc123_doc.pdf"
        target.write_bytes(b"data")
        result = _confine_to_storage(str(target))
        assert result == target.resolve()

    def test_path_traversal_blocked(self, tmp_path):
        evil = str(tmp_path / ".." / "etc" / "passwd")
        with pytest.raises(ValueError, match="STORAGE_PATH_TRAVERSAL_BLOCKED"):
            _confine_to_storage(evil)

    def test_absolute_escape_blocked(self, tmp_path):
        with pytest.raises(ValueError, match="STORAGE_PATH_TRAVERSAL_BLOCKED"):
            _confine_to_storage("/etc/passwd")

    def test_double_dot_in_middle_blocked(self, tmp_path):
        evil = str(tmp_path / "subdir" / ".." / ".." / "secret")
        with pytest.raises(ValueError, match="STORAGE_PATH_TRAVERSAL_BLOCKED"):
            _confine_to_storage(evil)

    def test_read_file_traversal_raises(self, tmp_path):
        with pytest.raises(ValueError, match="STORAGE_PATH_TRAVERSAL_BLOCKED"):
            read_file("/etc/passwd")

    def test_file_exists_traversal_returns_false(self, tmp_path):
        assert file_exists("/etc/passwd") is False

    def test_file_exists_traversal_never_raises(self, tmp_path):
        assert file_exists("/etc/shadow") is False

    def test_read_file_inside_storage_reads_data(self, tmp_path):
        target = tmp_path / "aabbcc_test.pdf"
        target.write_bytes(b"pdfdata")
        data = read_file(str(target))
        assert data == b"pdfdata"

    def test_storage_dir_itself_blocked_as_file(self, tmp_path):
        with pytest.raises((ValueError, IsADirectoryError)):
            read_file(str(tmp_path))

    def test_sibling_directory_blocked(self, tmp_path):
        sibling = tmp_path.parent / "sibling"
        with pytest.raises(ValueError, match="STORAGE_PATH_TRAVERSAL_BLOCKED"):
            _confine_to_storage(str(sibling / "file.pdf"))
