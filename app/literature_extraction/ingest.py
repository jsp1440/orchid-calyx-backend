from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from .models import AnalysisManifest, PaperKnowledge, PaperMetadata, SourceDocument


@dataclass(frozen=True, slots=True)
class IngestedDocument:
    source_path: Path
    raw_bytes: bytes
    raw_text: str
    content_hash: str


def ingest_text(path: str | Path) -> IngestedDocument:
    source_path = Path(path)
    raw_bytes = source_path.read_bytes()
    raw_text = raw_bytes.decode("utf-8")
    return IngestedDocument(
        source_path=source_path,
        raw_bytes=raw_bytes,
        raw_text=raw_text,
        content_hash=sha256(raw_bytes).hexdigest(),
    )


def read_text_exact(path: str | Path) -> str:
    """Decode UTF-8 without universal-newline translation.

    Character offsets are part of the evidence contract, so extractors must
    operate on exactly the same decoded text that ingestion hashed.
    """
    with Path(path).open("r", encoding="utf-8", newline="") as source:
        return source.read()


def build_empty_paper(
    document: IngestedDocument,
    *,
    pipeline_version: str = "0.2.0",
) -> PaperKnowledge:
    paper_id = f"paper-{document.content_hash}"
    analysis_id = sha256(
        f"{document.content_hash}\x1f{pipeline_version}".encode()
    ).hexdigest()
    return PaperKnowledge(
        paper_id=paper_id,
        source=SourceDocument(
            content_hash=document.content_hash,
            media_type="text/plain",
            original_filename=document.source_path.name,
            storage_uri=str(document.source_path),
        ),
        metadata=PaperMetadata(),
        analysis_manifest=AnalysisManifest(
            analysis_id=analysis_id,
            analysis_version=1,
            created_at=__import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ),
            pipeline_version=pipeline_version,
            status="pending",
            input_fingerprint=document.content_hash,
        ),
    )
