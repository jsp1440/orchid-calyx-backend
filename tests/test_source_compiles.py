"""Every tracked Python source file must compile.

``main`` once carried ``app/source_federation/acquisition_ledger.py``,
``app/federation/shared_firecrawl.py`` and ``tests/test_shared_firecrawl.py``
with literal ``\\n`` escapes pasted in place of line breaks. None of them could
be imported, and nothing in CI compiled them before they landed.

This test compiles the whole tracked tree -- application code, scripts,
runtime helpers, harvesters, migrations and the tests themselves -- in memory,
without writing bytecode, and reports every file that fails.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

_SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
}


def _tracked_python_files() -> list[Path]:
    git = shutil.which("git")
    if git and (REPO_ROOT / ".git").exists():
        listing = subprocess.run(
            [git, "ls-files", "-z", "--", "*.py"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
        ).stdout
        names = [name for name in listing.decode("utf-8").split("\0") if name]
        return [REPO_ROOT / name for name in names]
    # Source archives without git metadata: walk the tree instead.
    found: list[Path] = []
    for directory, subdirs, files in os.walk(REPO_ROOT):
        subdirs[:] = [name for name in subdirs if name not in _SKIP_DIRS]
        found.extend(Path(directory) / name for name in files if name.endswith(".py"))
    return found


def _compile_failures(paths: list[Path], root: Path = REPO_ROOT) -> list[str]:
    failures: list[str] = []
    for path in paths:
        if not path.is_file():
            # Tracked but deleted in the working tree; nothing to compile.
            continue
        try:
            compile(path.read_bytes(), str(path), "exec", dont_inherit=True)
        except (SyntaxError, ValueError) as exc:
            relative = path.relative_to(root)
            line = getattr(exc, "lineno", None)
            failures.append(f"{relative}:{line}: {type(exc).__name__}: {exc}")
    return failures


def test_python_source_tree_is_non_trivial() -> None:
    paths = _tracked_python_files()
    # Guards against a listing that silently finds nothing and "passes".
    assert len(paths) > 100
    assert REPO_ROOT / "app" / "main.py" in paths


def test_every_tracked_python_file_compiles() -> None:
    failures = _compile_failures(_tracked_python_files())
    assert not failures, "Python files that do not compile:\n" + "\n".join(failures)


def test_compile_check_reports_literal_escaped_newline(tmp_path: Path) -> None:
    # The exact defect shape that reached main: "\\n" typed where a line
    # break belongs. The check must name the file, not pass it.
    broken = tmp_path / "broken.py"
    broken.write_text("def f():\\n    return 1\n", encoding="utf-8")
    clean = tmp_path / "clean.py"
    clean.write_text("def f():\n    return 1\n", encoding="utf-8")

    failures = _compile_failures([broken, clean], root=tmp_path)

    assert len(failures) == 1
    assert failures[0].startswith("broken.py:1: SyntaxError:")
