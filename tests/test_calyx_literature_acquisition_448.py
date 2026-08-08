from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.candidate_knowledge.repository import MemoryCandidateRepository
from app.candidate_knowledge.service import CandidateExtractionService
from app.parallel_platform.brain_candidate_handoff import handoff_brain_candidate
from app.routers import literature_acquisition as api
from app.security import verify_owner_or_api_key
from runtime import literature_acquisition as runtime
from runtime.literature_acquisition import LiteratureAcquisitionService

TEXT = (
    b"Cattleya labiata occurs in seasonal forest.\n\n"
    b"This observation supports a habitat association."
)


def _taxonomy(path: Path) -> Path:
    rows = [
        {"taxon_key": "id:1001", "scientific_name": "Cattleya labiata"},
        {"taxon_key": "id:1002", "scientific_name": "Laelia purpurata"},
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


def test_doi_url_and_upload_identity_contracts_are_deterministic(tmp_path: Path):
    service = LiteratureAcquisitionService(tmp_path / "lit")
    doi = service.intake_bytes("paper.txt", TEXT, source_ref="10.1234/ABC.1")
    replay = service.intake_bytes("paper.txt", TEXT, source_ref="https://doi.org/10.1234/abc.1")
    url = service.intake_bytes("paper.txt", TEXT, source_ref="https://example.org/paper")
    upload = service.intake_bytes("paper.txt", TEXT)

    assert doi["run_id"] == replay["run_id"]
    assert doi["source_type"] == "doi"
    assert url["source_type"] == "url"
    assert upload["source_type"] == "uploaded_file"
    assert len(doi["source_sha256"]) == 64
    assert len(doi["extraction_sha256"]) == 64
    assert doi["ready_for_publication"] is False


def test_exact_evidence_spans_are_preserved(tmp_path: Path):
    service = LiteratureAcquisitionService(tmp_path / "lit")
    result = service.intake_bytes("paper.txt", TEXT)
    evidence = service.evidence(result["run_id"])
    extracted = (tmp_path / "lit" / "runs" / result["run_id"] / "extracted.txt").read_text()

    assert evidence["total"] == 2
    for span in evidence["items"]:
        assert extracted[span["char_start"] : span["char_end"]] == span["text"]
        assert len(span["sha256"]) == 64


def test_native_and_scanned_pdf_detection_contracts(tmp_path: Path, monkeypatch):
    class NativePage:
        def extract_text(self):
            return "Cattleya labiata has a long floral tube with pollination context."

    class NativeReader:
        def __init__(self, _stream):
            self.pages = [NativePage()]

    monkeypatch.setattr(runtime, "PdfReader", NativeReader)
    service = LiteratureAcquisitionService(tmp_path / "native")
    native = service.intake_bytes("paper.pdf", b"%PDF-native-fixture")
    assert native["document_type"] == "native_pdf"
    assert native["ocr_required"] is False

    class BlankPage:
        def extract_text(self):
            return ""

    class BlankReader:
        def __init__(self, _stream):
            self.pages = [BlankPage()]

    monkeypatch.setattr(runtime, "PdfReader", BlankReader)
    scanned = LiteratureAcquisitionService(tmp_path / "scanned").intake_bytes(
        "scan.pdf", b"%PDF-scanned-fixture"
    )
    assert scanned["document_type"] == "scanned_pdf"
    assert scanned["ocr_required"] is True
    assert scanned["live_ocr_authorized"] is False
    assert scanned["decision"] == "OCR_REQUIRED"


def test_taxonomy_reconciliation_exposes_unmatched_review(tmp_path: Path):
    taxonomy = _taxonomy(tmp_path / "taxonomy.jsonl")
    service = LiteratureAcquisitionService(tmp_path / "lit")
    result = service.intake_bytes("paper.txt", TEXT)
    reconciled = service.reconcile_taxa(
        result["run_id"],
        [
            {"scientific_name": "Cattleya labiata"},
            {"scientific_name": "Mystery orchid"},
        ],
        taxonomy_staging_path=taxonomy,
    )

    assert reconciled["matched"] == 1
    assert reconciled["unmatched"] == 1
    assert reconciled["review_required"] is True
    assert reconciled["items"][0]["canonical_taxon_id"] == "id:1001"


def test_candidate_handoff_preserves_claim_counterevidence_confidence_and_provenance(
    tmp_path: Path, monkeypatch
):
    repository = MemoryCandidateRepository()
    candidate_service = CandidateExtractionService(repository)
    monkeypatch.setattr(
        runtime,
        "handoff_brain_candidate",
        lambda request: handoff_brain_candidate(request, (repository, candidate_service)),
    )
    service = LiteratureAcquisitionService(tmp_path / "lit")
    result = service.intake_bytes("paper.txt", TEXT, source_ref="10.9999/orchid.1")
    text = (tmp_path / "lit" / "runs" / result["run_id"] / "extracted.txt").read_text()
    sentence = "Cattleya labiata occurs in seasonal forest."
    start = text.index(sentence)
    end = start + len(sentence)
    payload = {
        "domain": "ecology",
        "subject": "Cattleya labiata",
        "predicate": "occurs_in_habitat",
        "object_value": "seasonal forest",
        "confidence": 0.82,
        "char_start": start,
        "char_end": end,
        "contradiction": False,
    }
    first = service.handoff_candidates(result["run_id"], [payload])
    replay = service.handoff_candidates(result["run_id"], [payload])

    assert first["total_handoffs"] == 1
    assert replay["total_handoffs"] == 1
    assert first["handoffs"][0]["handoff_id"] == replay["handoffs"][0]["handoff_id"]
    assert first["handoffs"][0]["confidence"] == 0.82
    assert first["handoffs"][0]["contradiction"] is False
    assert len(first["handoffs"][0]["evidence_sha256"]) == 64
    assert first["handoffs"][0]["candidate_ids"]
    assert first["published"] is False
    assert first["graph_mutation"] is False


def test_candidate_handoff_rejects_invalid_span(tmp_path: Path):
    service = LiteratureAcquisitionService(tmp_path / "lit")
    result = service.intake_bytes("paper.txt", TEXT)
    try:
        service.handoff_candidates(
            result["run_id"],
            [
                {
                    "domain": "ecology",
                    "subject": "Cattleya labiata",
                    "predicate": "occurs_in_habitat",
                    "object_value": "forest",
                    "confidence": 0.8,
                    "char_start": 0,
                    "char_end": 99999,
                }
            ],
        )
    except ValueError as exc:
        assert "LITERATURE_EVIDENCE_SPAN_INVALID" in str(exc)
    else:
        raise AssertionError("invalid evidence span must fail closed")


def test_protected_mission_control_api(tmp_path: Path, monkeypatch):
    service = LiteratureAcquisitionService(tmp_path / "lit")
    monkeypatch.setattr(api, "_service", lambda: service)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {"actor": "test-owner"}
    client = TestClient(app)

    intake = client.post(
        "/brain/mission-control/literature/intake",
        files={"source": ("paper.txt", TEXT, "text/plain")},
        data={"source_ref": "https://example.org/paper"},
    )
    assert intake.status_code == 200
    run_id = intake.json()["run_id"]

    evidence = client.get(f"/brain/mission-control/literature/{run_id}/evidence")
    assert evidence.status_code == 200
    assert evidence.json()["total"] == 2

    readiness = client.get(f"/brain/mission-control/literature/{run_id}/readiness")
    assert readiness.status_code == 200
    assert readiness.json()["scientific_publication_authorized"] is False


def test_upload_bounds_and_invalid_source_ref_fail_closed(tmp_path: Path):
    service = LiteratureAcquisitionService(tmp_path / "lit", maximum_bytes=3)
    try:
        service.intake_bytes("paper.txt", TEXT)
    except ValueError as exc:
        assert "maximum_bytes" in str(exc)
    else:
        raise AssertionError("oversized literature source must fail")

    normal = LiteratureAcquisitionService(tmp_path / "normal")
    try:
        normal.intake_bytes("paper.txt", TEXT, source_ref="not-a-doi-or-url")
    except ValueError as exc:
        assert "LITERATURE_SOURCE_REF_INVALID" in str(exc)
    else:
        raise AssertionError("invalid source ref must fail")
