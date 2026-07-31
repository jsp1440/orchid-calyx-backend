"""Institutional Archive Manager.

BUILD-080 provides resumable, provenance-preserving institutional archive ingestion.
The subsystem is intentionally isolated from canonical Knowledge Graph storage.
"""

from app.archive.importer import ArchiveImporter

__all__ = ["ArchiveImporter"]
