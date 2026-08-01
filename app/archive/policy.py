from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class ArchivePolicyError(ValueError):
    """Raised when an archive request violates deployment policy."""


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ArchivePolicyError(f"{name} must be an integer") from exc
    if value < 1:
        raise ArchivePolicyError(f"{name} must be positive")
    return value


@dataclass(frozen=True, slots=True)
class ArchivePolicy:
    allowed_roots: tuple[Path, ...]
    max_file_bytes: int = 100 * 1024 * 1024
    max_zip_members: int = 10_000
    max_zip_uncompressed_bytes: int = 2 * 1024 * 1024 * 1024
    max_zip_expansion_ratio: int = 200
    max_path_depth: int = 40

    @classmethod
    def from_environment(cls) -> "ArchivePolicy":
        raw_roots = os.getenv("ARCHIVE_ALLOWED_ROOTS", "")
        roots = tuple(
            Path(value).expanduser().resolve()
            for value in raw_roots.split(os.pathsep)
            if value.strip()
        )
        return cls(
            allowed_roots=roots,
            max_file_bytes=_positive_int("ARCHIVE_MAX_FILE_BYTES", 100 * 1024 * 1024),
            max_zip_members=_positive_int("ARCHIVE_MAX_ZIP_MEMBERS", 10_000),
            max_zip_uncompressed_bytes=_positive_int(
                "ARCHIVE_MAX_ZIP_UNCOMPRESSED_BYTES", 2 * 1024 * 1024 * 1024
            ),
            max_zip_expansion_ratio=_positive_int("ARCHIVE_MAX_ZIP_EXPANSION_RATIO", 200),
            max_path_depth=_positive_int("ARCHIVE_MAX_PATH_DEPTH", 40),
        )

    def authorize_source(self, source: Path) -> Path:
        resolved = source.expanduser().resolve()
        if not self.allowed_roots:
            raise ArchivePolicyError(
                "archive imports are disabled until ARCHIVE_ALLOWED_ROOTS is configured"
            )
        if not any(resolved == root or root in resolved.parents for root in self.allowed_roots):
            raise ArchivePolicyError("archive source is outside approved roots")
        if not resolved.exists():
            raise ArchivePolicyError("archive source does not exist")
        return resolved

    def validate_path(self, path: Path, root: Path) -> None:
        relative = path.resolve().relative_to(root.resolve())
        if len(relative.parts) > self.max_path_depth:
            raise ArchivePolicyError("archive path exceeds maximum depth")
        if path.is_file() and path.stat().st_size > self.max_file_bytes:
            raise ArchivePolicyError("archive file exceeds maximum size")
