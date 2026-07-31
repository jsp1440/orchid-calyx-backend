from __future__ import annotations

import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ScannedFile:
    path: Path
    source_root: Path
    relative_path: str
    size_bytes: int
    media_type: str | None = None


class ArchiveScanner:
    def scan(self, root: Path) -> Iterator[ScannedFile]:
        root = root.resolve()
        if not root.exists():
            raise FileNotFoundError(root)
        for path in sorted(root.rglob("*")):
            if path.is_file():
                yield ScannedFile(
                    path,
                    root,
                    path.relative_to(root).as_posix(),
                    path.stat().st_size,
                )

    def extract_zip(self, archive: Path, destination: Path) -> Path:
        destination.mkdir(parents=True, exist_ok=True)
        destination_root = destination.resolve()
        with zipfile.ZipFile(archive) as handle:
            for member in handle.infolist():
                target = (destination / member.filename).resolve()
                if destination_root not in target.parents and target != destination_root:
                    raise ValueError(f"unsafe ZIP member: {member.filename}")
            handle.extractall(destination)
        return destination
