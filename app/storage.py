import os
import hashlib
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

STORAGE_DIR = Path(os.getenv("REFERENCE_DOCS_DIR", "/home/runner/workspace/data/reference_docs"))
INTAKE_STORAGE_DIR = Path(os.getenv("INTAKE_STORAGE_DIR", str(STORAGE_DIR / "intake")))


def sanitize_filename(filename: str) -> str:
    """Return a display-only filename; storage keys never trust this value."""
    name = Path(filename.replace("\\", "/")).name
    name = re.sub(r"[\x00-\x1f<>:\"/\\|?*]+", "_", name).strip(" .")
    return (name[:240] or "unnamed")


@dataclass(frozen=True)
class StoredOriginal:
    storage_key: str
    sha256: str
    byte_size: int
    display_filename: str


class LocalImmutableStorage:
    """Private local adapter. Production must mount durable private storage or replace it."""

    def __init__(self, root: Path = INTAKE_STORAGE_DIR):
        self.root = root

    def preserve(self, data: bytes, filename: str) -> StoredOriginal:
        digest = compute_sha256(data)
        display = sanitize_filename(filename)
        key = f"sha256/{digest[:2]}/{digest}"
        target = self.root / key
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if compute_sha256(target.read_bytes()) != digest:
                raise RuntimeError("Immutable storage hash collision")
        else:
            fd, temporary = tempfile.mkstemp(prefix="intake-", dir=target.parent)
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, target)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        return StoredOriginal(key, digest, len(data), display)

    def read(self, storage_key: str) -> bytes:
        if not re.fullmatch(r"sha256/[0-9a-f]{2}/[0-9a-f]{64}", storage_key):
            raise ValueError("Invalid storage key")
        return (self.root / storage_key).read_bytes()


def ensure_storage_dir():
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)


def compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def save_file(data: bytes, filename: str) -> str:
    ensure_storage_dir()
    sha256 = compute_sha256(data)
    safe_filename = f"{sha256}_{filename}"
    file_path = STORAGE_DIR / safe_filename
    with open(file_path, "wb") as f:
        f.write(data)
    return str(file_path)


def read_file(file_path: str) -> bytes:
    with open(file_path, "rb") as f:
        return f.read()


def file_exists(file_path: str) -> bool:
    return Path(file_path).exists()
