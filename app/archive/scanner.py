from __future__ import annotations

import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from app.archive.policy import ArchivePolicy, ArchivePolicyError


@dataclass(frozen=True, slots=True)
class ScannedFile:
    path: Path
    source_root: Path
    relative_path: str
    size_bytes: int
    media_type: str | None = None


class ArchiveScanner:
    def __init__(self, policy: ArchivePolicy | None = None) -> None:
        self.policy = policy or ArchivePolicy.from_environment()

    def scan(self, root: Path) -> Iterator[ScannedFile]:
        root = root.resolve()
        if not root.exists():
            raise FileNotFoundError(root)
        for path in sorted(root.rglob("*")):
            if path.is_file():
                self.policy.validate_path(path, root)
                yield ScannedFile(
                    path,
                    root,
                    path.relative_to(root).as_posix(),
                    path.stat().st_size,
                )

    def extract_zip(self, archive: Path, destination: Path) -> Path:
        if archive.stat().st_size > self.policy.max_file_bytes:
            raise ArchivePolicyError("ZIP archive exceeds maximum file size")
        destination.mkdir(parents=True, exist_ok=True)
        destination_root = destination.resolve()
        with zipfile.ZipFile(archive) as handle:
            members = handle.infolist()
            if len(members) > self.policy.max_zip_members:
                raise ArchivePolicyError("ZIP archive contains too many members")
            total_uncompressed = sum(member.file_size for member in members)
            total_compressed = sum(max(member.compress_size, 1) for member in members)
            if total_uncompressed > self.policy.max_zip_uncompressed_bytes:
                raise ArchivePolicyError("ZIP archive exceeds uncompressed size limit")
            if total_uncompressed / max(total_compressed, 1) > self.policy.max_zip_expansion_ratio:
                raise ArchivePolicyError("ZIP archive expansion ratio exceeds safety limit")
            for member in members:
                target = (destination / member.filename).resolve()
                if destination_root not in target.parents and target != destination_root:
                    raise ArchivePolicyError(f"unsafe ZIP member: {member.filename}")
                relative = target.relative_to(destination_root)
                if len(relative.parts) > self.policy.max_path_depth:
                    raise ArchivePolicyError("ZIP member exceeds maximum path depth")
                if member.file_size > self.policy.max_file_bytes:
                    raise ArchivePolicyError("ZIP member exceeds maximum file size")
            handle.extractall(destination)
        return destination
