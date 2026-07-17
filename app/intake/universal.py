import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

MAX_FILE_BYTES = 50 * 1024 * 1024
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".csv", ".json", ".xlsx", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".zip"}
TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".json"}

CLASSIFICATIONS = (
    "scientific publication", "research report", "Kimi analysis", "Julius analysis",
    "technical audit", "scientific audit", "build report", "software specification",
    "strategic plan", "grant application", "grant guideline or solicitation", "grant report",
    "project-management document", "dataset", "spreadsheet", "bibliography", "correspondence",
    "administrative record", "image or illustration", "source-code artifact", "unknown",
    "potentially unrelated",
)

@dataclass
class CandidateAnalysis:
    document_type: str
    classification_confidence: float
    relevance: str
    relevance_confidence: float
    explanation: str
    extracted_text: str | None = None
    extraction_status: str = "NOT_SUPPORTED"
    candidate_dates: list[dict] = field(default_factory=list)
    grant_candidate: dict | None = None
    external_sources: list[dict] = field(default_factory=list)


def validate_file(filename: str, data: bytes, max_bytes: int = MAX_FILE_BYTES) -> str:
    extension = Path(filename).suffix.lower()
    if len(data) > max_bytes:
        raise ValueError("FILE_TOO_LARGE")
    if extension not in SUPPORTED_EXTENSIONS:
        raise ValueError("UNSUPPORTED_FILE_TYPE")
    if extension == ".zip":
        inspect_zip(data)
    return extension


def inspect_zip(data: bytes, max_entries: int = 1000, max_expanded_bytes: int = 250 * 1024 * 1024) -> list[str]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > max_entries or sum(item.file_size for item in infos) > max_expanded_bytes:
                raise ValueError("UNSAFE_ARCHIVE_LIMIT")
            names = []
            for item in infos:
                path = Path(item.filename.replace("\\", "/"))
                if item.flag_bits & 0x1:
                    raise ValueError("ENCRYPTED_ARCHIVE_UNSUPPORTED")
                if path.is_absolute() or ".." in path.parts:
                    raise ValueError("ZIP_PATH_TRAVERSAL")
                names.append(item.filename)
            return names
    except zipfile.BadZipFile as exc:
        raise ValueError("MALFORMED_ZIP") from exc


def extract_safe_text(extension: str, data: bytes) -> tuple[str | None, str]:
    if extension not in TEXT_EXTENSIONS:
        return None, "PENDING_SPECIALIZED_PARSER"
    try:
        text = data.decode("utf-8-sig")
        if extension == ".json":
            json.loads(text)
        return text[:2_000_000], "EXTRACTED"
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, "FAILED"


def classify(filename: str, text: str | None) -> CandidateAnalysis:
    extension = Path(filename).suffix.lower()
    body = (text or "")[:200_000]
    lower = f"{filename}\n{body}".lower()
    rules = [
        ("grant guideline or solicitation", ("request for proposals", "eligibility", "application deadline")),
        ("grant report", ("grant progress report", "final report", "award number")),
        ("grant application", ("grant application", "amount requested", "proposed budget", "mbz species conservation fund")),
        ("Kimi analysis", ("kimi",)), ("Julius analysis", ("julius",)),
        ("build report", ("build-", "implementation report")),
        ("technical audit", ("technical audit", "repository audit")),
        ("scientific audit", ("scientific audit",)),
        ("software specification", ("acceptance criteria", "api endpoint", "software specification")),
        ("strategic plan", ("strategic plan", "roadmap")),
        ("scientific publication", ("doi:", "abstract", "references")),
        ("bibliography", ("bibliography",)),
    ]
    document_type, evidence = "unknown", []
    for candidate, markers in rules:
        evidence = [marker for marker in markers if marker in lower]
        if evidence:
            document_type = candidate
            break
    if document_type == "unknown":
        if extension == ".xlsx": document_type = "spreadsheet"
        elif extension in {".csv", ".json"}: document_type = "dataset"
        elif extension in {".png", ".jpg", ".jpeg", ".webp", ".gif"}: document_type = "image or illustration"

    orchid_markers = ("orchid", "orchidaceae", "orchid continuum", "calyx", "mycorrhiza", "pollination", "taxonomy", "species dossier", "conservation hotspot", "grant", "build-")
    relevance_hits = [marker for marker in orchid_markers if marker in lower]
    if len(relevance_hits) >= 3: relevance, relevance_confidence = "strongly relevant", .92
    elif relevance_hits: relevance, relevance_confidence = "probably relevant", .72
    else: relevance, relevance_confidence = "uncertain", .40
    explanation = "; ".join(([f"type signals: {', '.join(evidence)}"] if evidence else [f"type inferred from {extension or 'content'}"]) + ([f"relevance signals: {', '.join(relevance_hits[:6])}"] if relevance_hits else ["no decisive relevance signal; human review required"]))

    urls = []
    for match in re.finditer(r"https?://[^\s<>'\"]+", body, re.I):
        value = match.group(0).rstrip(".,;)")
        kind = "api" if "api" in value.lower() else "repository" if "github.com" in value.lower() else "dataset" if any(x in value.lower() for x in ("zenodo", "dataset", "dwca")) else "webpage"
        urls.append({"url": value, "kind": kind, "evidence_offset": match.start(), "contacted": False})
    dates = [{"date_text": m.group(0), "date_type": "date mentioned in text", "confidence": .55, "evidence_offset": m.start()} for m in re.finditer(r"\b(?:20\d{2}-\d{2}-\d{2}|[A-Z][a-z]+ \d{1,2}, 20\d{2})\b", body)]
    grant = None
    if document_type.startswith("grant"):
        grant = {"verification_state": "UNREVIEWED", "status": "candidate", "funder": None, "program": None, "deliverable_candidates": [], "milestone_candidates": [], "relationship_model": "grant -> commitment/deliverable -> milestone -> evidence -> status -> deadline"}
    return CandidateAnalysis(document_type, .86 if evidence else .55, relevance, relevance_confidence, explanation, text, "EXTRACTED" if text is not None else "PENDING_SPECIALIZED_PARSER", dates, grant, urls)
