"""Bounded Literature Intelligence acquisition/evidence binding for CALYX issue #448.

This module is network-independent. Callers supply source bytes plus an optional DOI or
URL reference. It preserves immutable source/revision/run identities, detects native
versus scanned PDFs without OCR, creates exact spans over extracted text, supports
reviewed-taxonomy reconciliation, and hands explicitly proposed claims into the
existing Candidate Knowledge boundary. It never publishes science or mutates the KG.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pypdf import PdfReader

from app.parallel_platform.brain_candidate_handoff import (
    BrainCandidateHandoffRequest,
    BrainEvidenceAnchor,
    handoff_brain_candidate,
)
from runtime.taxonomy_preflight import normalize

LITERATURE_SCHEMA_VERSION = "1.0.0"
EXTRACTOR_VERSION = "calyx-literature-448-v1"
DOI_RE = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/)?(10\.\d{4,9}/\S+)$", re.IGNORECASE)
SAFE_ID_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _json(path: Path, payload: Any) -> None:
    _atomic_write(path, json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _integer_id(value: str) -> int:
    return int(hashlib.sha256(value.encode()).hexdigest()[:15], 16) + 1


def _safe_filename(value: str) -> str:
    name = Path(value).name.strip()
    if not name or name in {".", ".."}:
        raise ValueError("LITERATURE_FILENAME_REQUIRED")
    return SAFE_ID_RE.sub("_", name)[:180]


def _source_identity(source_ref: str | None, filename: str) -> tuple[str, str]:
    ref = normalize(source_ref)
    if ref:
        match = DOI_RE.match(ref)
        if match:
            doi = match.group(1).rstrip(".,;)").casefold()
            return "doi", f"doi:{doi}"
        parsed = urlparse(ref)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return "url", ref
        raise ValueError("LITERATURE_SOURCE_REF_INVALID")
    return "uploaded_file", f"upload:{_safe_filename(filename)}"


def _extract_text(filename: str, content: bytes) -> tuple[str, str, list[dict[str, Any]]]:
    is_pdf = filename.casefold().endswith(".pdf") or content.startswith(b"%PDF")
    if is_pdf:
        try:
            reader = PdfReader(io.BytesIO(content))
        except Exception as exc:
            raise ValueError(f"LITERATURE_PDF_INVALID:{exc.__class__.__name__}") from exc
        pages: list[dict[str, Any]] = []
        chunks: list[str] = []
        cursor = 0
        for page_number, page in enumerate(reader.pages, start=1):
            extracted = page.extract_text() or ""
            if chunks:
                chunks.append("\n\n")
                cursor += 2
            start = cursor
            chunks.append(extracted)
            cursor += len(extracted)
            pages.append({"page_number": page_number, "char_start": start, "char_end": cursor})
        text = "".join(chunks)
        meaningful = len("".join(text.split())) >= 20
        return ("native_pdf" if meaningful else "scanned_pdf"), text, pages
    try:
        return "uploaded_text", content.decode("utf-8"), []
    except UnicodeDecodeError as exc:
        raise ValueError("LITERATURE_UNSUPPORTED_BINARY_UPLOAD") from exc


def _evidence_spans(text: str) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    pattern = re.compile(r"\S(?:.*?\S)?(?=\n\s*\n|\Z)", re.DOTALL)
    for index, match in enumerate(pattern.finditer(text), start=1):
        spans.append({
            "span_id": index,
            "char_start": match.start(),
            "char_end": match.end(),
            "sha256": _sha(match.group(0).encode("utf-8")),
            "text": match.group(0),
        })
    if not spans and text:
        spans.append({
            "span_id": 1,
            "char_start": 0,
            "char_end": len(text),
            "sha256": _sha(text.encode("utf-8")),
            "text": text,
        })
    return spans


def _norm_name(value: str) -> str:
    return " ".join(normalize(value).casefold().split())


class ReviewedTaxonIndex:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.by_name: dict[str, list[str]] = {}
        self.by_key: dict[str, str] = {}
        for row in rows:
            key = normalize(str(row.get("taxon_key") or ""))
            name = normalize(str(row.get("scientific_name") or ""))
            if not key or not name:
                continue
            self.by_key[key] = name
            self.by_name.setdefault(_norm_name(name), []).append(key)

    @classmethod
    def from_path(cls, path: Path | None) -> "ReviewedTaxonIndex":
        if path is None:
            return cls([])
        if not path.is_file():
            raise ValueError("configured taxonomy staging artifact is not a regular file")
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return cls(rows)

    def resolve(self, scientific_name: str, supplied_key: str = "") -> dict[str, Any]:
        if supplied_key and supplied_key in self.by_key:
            return {"state": "matched", "canonical_taxon_id": supplied_key, "method": "taxon_key"}
        keys = sorted(set(self.by_name.get(_norm_name(scientific_name), []))) if scientific_name else []
        if len(keys) == 1:
            return {"state": "matched", "canonical_taxon_id": keys[0], "method": "scientific_name_exact"}
        if len(keys) > 1:
            return {"state": "ambiguous", "canonical_taxon_id": None, "candidate_ids": keys, "method": "scientific_name_exact"}
        return {"state": "unmatched", "canonical_taxon_id": None, "candidate_ids": [], "method": "none"}


@dataclass(frozen=True)
class LiteratureIdentity:
    source_id: str
    revision_id: str
    run_id: str
    source_type: str
    document_type: str
    source_sha256: str
    extraction_sha256: str


class LiteratureAcquisitionService:
    def __init__(self, workspace: Path, *, maximum_bytes: int = 50 * 1024 * 1024) -> None:
        self.workspace = workspace
        self.maximum_bytes = maximum_bytes

    def _run_dir(self, run_id: str) -> Path:
        if not run_id or SAFE_ID_RE.sub("_", run_id) != run_id:
            raise ValueError("invalid run_id")
        return self.workspace / "runs" / run_id

    def intake_bytes(
        self,
        filename: str,
        content: bytes,
        *,
        source_ref: str | None = None,
        taxonomy_staging_path: Path | None = None,
    ) -> dict[str, Any]:
        if not content:
            raise ValueError("LITERATURE_CONTENT_REQUIRED")
        if len(content) > self.maximum_bytes:
            raise ValueError(f"literature source exceeds maximum_bytes={self.maximum_bytes}")
        clean_name = _safe_filename(filename)
        source_type, source_key = _source_identity(source_ref, clean_name)
        document_type, text, pages = _extract_text(clean_name, content)
        source_sha = _sha(content)
        extraction_sha = _sha(text.encode("utf-8"))
        source_id = f"src-{_sha(source_key.encode())[:20]}"
        revision_id = f"rev-{source_sha[:20]}"
        run_material = f"{source_id}:{revision_id}:{EXTRACTOR_VERSION}:{extraction_sha}"
        run_id = f"lit-{_sha(run_material.encode())[:20]}"
        root = self._run_dir(run_id)

        source_path = root / "source" / clean_name
        if source_path.exists() and source_path.read_bytes() != content:
            raise RuntimeError("immutable literature source conflict")
        if not source_path.exists():
            source_path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix=".literature-source.", dir=source_path.parent)
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, source_path)
            except Exception:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass
                raise

        spans = _evidence_spans(text)
        identity = LiteratureIdentity(
            source_id=source_id,
            revision_id=revision_id,
            run_id=run_id,
            source_type=source_type,
            document_type=document_type,
            source_sha256=source_sha,
            extraction_sha256=extraction_sha,
        )
        _atomic_write(root / "extracted.txt", text)
        _json(root / "evidence_spans.json", spans)
        _json(root / "taxonomy_review.json", [])
        _json(root / "candidate_handoffs.json", [])
        _json(root / "checkpoint.json", {
            "extraction_complete": document_type != "scanned_pdf",
            "ocr_required": document_type == "scanned_pdf",
            "candidate_handoff_count": 0,
            "complete": document_type != "scanned_pdf",
        })
        _json(root / "manifest.json", {
            "schema_version": LITERATURE_SCHEMA_VERSION,
            "extractor_version": EXTRACTOR_VERSION,
            "identity": asdict(identity),
            "filename": clean_name,
            "source_key": source_key,
            "source_byte_count": len(content),
            "extracted_character_count": len(text),
            "evidence_span_count": len(spans),
            "pages": pages,
            "taxonomy_staging_configured": taxonomy_staging_path is not None,
            "candidate_knowledge_authorized": True,
            "scientific_publication_authorized": False,
            "knowledge_graph_mutation_authorized": False,
            "live_ocr_authorized": False,
        })
        return self.readiness(run_id)

    def reconcile_taxa(self, run_id: str, taxa: list[dict[str, str]], *, taxonomy_staging_path: Path | None) -> dict[str, Any]:
        root = self._run_dir(run_id)
        if not (root / "manifest.json").exists():
            raise FileNotFoundError(f"unknown literature run: {run_id}")
        index = ReviewedTaxonIndex.from_path(taxonomy_staging_path)
        results: list[dict[str, Any]] = []
        for item in taxa:
            name = normalize(item.get("scientific_name"))
            supplied = normalize(item.get("taxon_key"))
            resolution = index.resolve(name, supplied)
            results.append({"scientific_name": name, "supplied_taxon_key": supplied or None, **resolution})
        _json(root / "taxonomy_review.json", results)
        return {
            "run_id": run_id,
            "matched": sum(item["state"] == "matched" for item in results),
            "ambiguous": sum(item["state"] == "ambiguous" for item in results),
            "unmatched": sum(item["state"] == "unmatched" for item in results),
            "items": results,
            "review_required": any(item["state"] != "matched" for item in results),
        }

    def handoff_candidates(self, run_id: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
        root = self._run_dir(run_id)
        manifest_path = root / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"unknown literature run: {run_id}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        text = (root / "extracted.txt").read_text(encoding="utf-8")
        handoffs = json.loads((root / "candidate_handoffs.json").read_text(encoding="utf-8"))
        existing_ids = {item["handoff_id"] for item in handoffs}
        outputs: list[dict[str, Any]] = []
        for candidate in candidates:
            start = int(candidate.get("char_start", -1))
            end = int(candidate.get("char_end", -1))
            if start < 0 or end <= start or end > len(text):
                raise ValueError("LITERATURE_EVIDENCE_SPAN_INVALID")
            evidence_text = text[start:end]
            if not evidence_text.strip():
                raise ValueError("LITERATURE_EVIDENCE_SPAN_EMPTY")
            confidence = float(candidate.get("confidence", -1))
            if not 0 <= confidence <= 1:
                raise ValueError("LITERATURE_CONFIDENCE_INVALID")
            domain = normalize(candidate.get("domain"))
            subject = normalize(candidate.get("subject"))
            predicate = normalize(candidate.get("predicate"))
            object_value = candidate.get("object_value")
            if not domain or not subject or not predicate or object_value is None:
                raise ValueError("LITERATURE_CANDIDATE_FIELDS_REQUIRED")
            contradiction = bool(candidate.get("contradiction", False))
            handoff_material = _stable_json({
                "run_id": run_id,
                "domain": domain,
                "subject": subject,
                "predicate": predicate,
                "object_value": object_value,
                "confidence": confidence,
                "char_start": start,
                "char_end": end,
                "contradiction": contradiction,
            })
            handoff_id = f"handoff-{_sha(handoff_material.encode())[:20]}"
            if handoff_id in existing_ids:
                outputs.append(next(item for item in handoffs if item["handoff_id"] == handoff_id))
                continue
            source_object_id = _integer_id(manifest["identity"]["source_id"])
            revision_numeric = _integer_id(manifest["identity"]["revision_id"])
            run_numeric = _integer_id(run_id)
            request = BrainCandidateHandoffRequest(
                reasoning_id=handoff_id,
                domain=domain,
                subject=subject,
                predicate=predicate,
                object_value=str(object_value),
                confidence=confidence,
                evidence_text=evidence_text,
                source_object_type="literature_revision",
                source_object_id=source_object_id,
                revision_id=revision_numeric,
                extraction_run_id=run_numeric,
                source_anchors=[BrainEvidenceAnchor(
                    anchor_id=1,
                    ordered_span=0,
                    char_start=start,
                    char_end=end,
                    locator={"literature_run_id": run_id, "source_sha256": manifest["identity"]["source_sha256"]},
                )],
                provenance={
                    "literature_run_id": run_id,
                    "source_id": manifest["identity"]["source_id"],
                    "revision_id": manifest["identity"]["revision_id"],
                    "source_sha256": manifest["identity"]["source_sha256"],
                    "extraction_sha256": manifest["identity"]["extraction_sha256"],
                },
                qualifiers={"contradiction": contradiction, "claim_state": "counterevidence" if contradiction else "support"},
                display_policy="INTERNAL_REVIEW_ONLY",
                internal_use_permission=True,
            )
            result = handoff_brain_candidate(request)
            record = {
                "handoff_id": handoff_id,
                "candidate_run_id": result["candidate_run_id"],
                "candidate_ids": result["candidate_ids"],
                "contradiction": contradiction,
                "confidence": confidence,
                "char_start": start,
                "char_end": end,
                "evidence_sha256": _sha(evidence_text.encode("utf-8")),
                "review_required": True,
                "published": False,
            }
            handoffs.append(record)
            existing_ids.add(handoff_id)
            outputs.append(record)
        _json(root / "candidate_handoffs.json", handoffs)
        checkpoint = json.loads((root / "checkpoint.json").read_text(encoding="utf-8"))
        checkpoint["candidate_handoff_count"] = len(handoffs)
        _json(root / "checkpoint.json", checkpoint)
        return {"run_id": run_id, "handoffs": outputs, "total_handoffs": len(handoffs), "published": False, "graph_mutation": False}

    def evidence(self, run_id: str, *, offset: int = 0, limit: int = 100) -> dict[str, Any]:
        if offset < 0 or limit < 1 or limit > 500:
            raise ValueError("LITERATURE_EVIDENCE_BOUNDS_INVALID")
        root = self._run_dir(run_id)
        path = root / "evidence_spans.json"
        if not path.exists():
            raise FileNotFoundError(f"unknown literature run: {run_id}")
        spans = json.loads(path.read_text(encoding="utf-8"))
        return {"run_id": run_id, "total": len(spans), "offset": offset, "limit": limit, "items": spans[offset:offset + limit]}

    def readiness(self, run_id: str) -> dict[str, Any]:
        root = self._run_dir(run_id)
        manifest_path = root / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"unknown literature run: {run_id}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        checkpoint = json.loads((root / "checkpoint.json").read_text(encoding="utf-8"))
        taxonomy = json.loads((root / "taxonomy_review.json").read_text(encoding="utf-8"))
        return {
            "schema_version": LITERATURE_SCHEMA_VERSION,
            "run_id": run_id,
            "identity": manifest["identity"],
            "source_type": manifest["identity"]["source_type"],
            "document_type": manifest["identity"]["document_type"],
            "source_sha256": manifest["identity"]["source_sha256"],
            "extraction_sha256": manifest["identity"]["extraction_sha256"],
            "evidence_span_count": manifest["evidence_span_count"],
            "taxonomy_review_count": len(taxonomy),
            "taxonomy_unresolved_count": sum(item.get("state") != "matched" for item in taxonomy),
            "candidate_handoff_count": int(checkpoint.get("candidate_handoff_count", 0)),
            "ocr_required": bool(checkpoint.get("ocr_required")),
            "extraction_complete": bool(checkpoint.get("extraction_complete")),
            "decision": "OCR_REQUIRED" if checkpoint.get("ocr_required") else "REVIEW_ONLY",
            "ready_for_review": bool(checkpoint.get("extraction_complete")),
            "ready_for_publication": False,
            "scientific_publication_authorized": False,
            "knowledge_graph_mutation_authorized": False,
            "live_ocr_authorized": False,
        }
