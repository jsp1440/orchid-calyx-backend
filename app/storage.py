import os
import hashlib
from pathlib import Path

STORAGE_DIR = Path(os.getenv("REFERENCE_DOCS_DIR", "/home/runner/workspace/data/reference_docs"))


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
