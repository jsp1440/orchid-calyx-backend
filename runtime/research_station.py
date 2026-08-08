"""Private, reproducible Research Station workspace for CALYX issue #453.

The workspace preserves project-scoped provenance and immutable notebook revisions. It
can bind existing Literature Intelligence and Candidate Knowledge evidence without
becoming a publication authority, laboratory controller, or Knowledge Graph writer.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.calyx_orchestrator.artifact_registry import ImmutableArtifactRegistry
from runtime.literature_acquisition import LiteratureAcquisitionService

RESEARCH_SCHEMA_VERSION = "calyx-research-station/v1"
PROJECT_STATES = {"planned", "active", "blocked", "completed", "archived"}
TASK_STATES = {"todo", "in_progress", "blocked", "done"}
DECISIONS = {"accepted_for_project", "rejected", "deferred", "needs_review"}


def _text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _stable(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def research_root() -> Path:
    return Path(os.getenv("CALYX_RESEARCH_STATION_DIR", "/tmp/calyx/research-station"))


def literature_root() -> Path:
    return Path(os.getenv("CALYX_LITERATURE_ACQUISITION_PATH", "/tmp/calyx/literature-acquisition"))


@dataclass(frozen=True)
class ResearchProject:
    project_id: str
    title: str
    objective: str
    state: str
    created_at: str
    owner_key: str


@dataclass(frozen=True)
class ResearchQuestion:
    question_id: str
    project_id: str
    text: str
    rationale: str | None


@dataclass(frozen=True)
class Protocol:
    protocol_id: str
    project_id: str
    title: str
    version: str
    methods: str
    safety_notes: str | None


@dataclass(frozen=True)
class Sample:
    sample_id: str
    project_id: str
    sample_type: str
    label: str
    collected_at: str | None
    provenance: dict[str, Any]


@dataclass(frozen=True)
class Dataset:
    dataset_id: str
    project_id: str
    title: str
    checksum_sha256: str
    schema_ref: str | None
    provenance: dict[str, Any]


@dataclass(frozen=True)
class Claim:
    claim_id: str
    project_id: str
    statement: str
    confidence: float | None
    state: str
    provenance: dict[str, Any]


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    project_id: str
    claim_id: str | None
    attachment_id: str
    relation: str
    note: str | None


@dataclass(frozen=True)
class Decision:
    decision_id: str
    project_id: str
    subject_id: str
    decision: str
    rationale: str
    decided_by: str
    decided_at: str


class ResearchStationService:
    def __init__(
        self,
        workspace: Path | None = None,
        *,
        literature: LiteratureAcquisitionService | None = None,
        artifact_registry: ImmutableArtifactRegistry | None = None,
    ) -> None:
        self.workspace = workspace or research_root()
        self.literature = literature or LiteratureAcquisitionService(literature_root())
        self.artifact_registry = artifact_registry or ImmutableArtifactRegistry()

    @staticmethod
    def _owner_key(owner_id: str) -> str:
        owner = _text(owner_id)
        if not owner:
            raise ValueError("RESEARCH_OWNER_REQUIRED")
        return _sha(owner.casefold())[:24]

    def _root(self, owner_id: str, project_id: str | None = None) -> Path:
        root = self.workspace / "owners" / self._owner_key(owner_id)
        if project_id is None:
            return root
        clean = _text(project_id)
        if not clean or any(token in clean for token in ("/", "\\", "..")):
            raise ValueError("RESEARCH_PROJECT_ID_INVALID")
        return root / "projects" / clean

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(path.stem)
        return json.loads(path.read_text(encoding="utf-8"))

    def _project(self, owner_id: str, project_id: str) -> tuple[Path, dict[str, Any]]:
        root = self._root(owner_id, project_id)
        return root, self._read(root / "project.json")

    def create_project(self, owner_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        owner_key = self._owner_key(owner_id)
        title = _text(payload.get("title"))
        objective = _text(payload.get("objective"))
        created_at = _text(payload.get("created_at"))
        if not title or not objective or not created_at:
            raise ValueError("RESEARCH_PROJECT_FIELDS_REQUIRED")
        project_id = _text(payload.get("project_id")) or f"project-{_sha(owner_key + ':' + title.casefold())[:20]}"
        state = _text(payload.get("state") or "planned").casefold()
        if state not in PROJECT_STATES:
            raise ValueError("RESEARCH_PROJECT_STATE_INVALID")
        project = ResearchProject(project_id, title, objective, state, created_at, owner_key)
        record = {
            **asdict(project),
            "schema_version": RESEARCH_SCHEMA_VERSION,
            "private_by_default": True,
            "public_sharing_enabled": False,
            "scientific_publication_authorized": False,
            "live_laboratory_control": False,
            "production_deployment_authorized": False,
            "knowledge_graph_mutation_authorized": False,
        }
        root = self._root(owner_id, project_id)
        path = root / "project.json"
        if path.exists():
            existing = self._read(path)
            if existing != record:
                raise ValueError("RESEARCH_PROJECT_IMMUTABLE_CONFLICT")
            return {"created": False, "project": existing}
        _atomic(path, record)
        return {"created": True, "project": record}

    def add_question(self, owner_id: str, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        root, _ = self._project(owner_id, project_id)
        text = _text(payload.get("text"))
        if not text:
            raise ValueError("RESEARCH_QUESTION_REQUIRED")
        question_id = _text(payload.get("question_id")) or f"q-{_sha(project_id + ':' + text)[:20]}"
        record = asdict(ResearchQuestion(question_id, project_id, text, _text(payload.get("rationale")) or None))
        return self._immutable_record(root, "questions", question_id, record)

    def add_protocol(self, owner_id: str, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        root, _ = self._project(owner_id, project_id)
        title, version, methods = (_text(payload.get(key)) for key in ("title", "version", "methods"))
        if not title or not version or not methods:
            raise ValueError("RESEARCH_PROTOCOL_FIELDS_REQUIRED")
        protocol_id = _text(payload.get("protocol_id")) or f"protocol-{_sha(project_id + ':' + title + ':' + version)[:20]}"
        record = asdict(Protocol(protocol_id, project_id, title, version, methods, _text(payload.get("safety_notes")) or None))
        return self._immutable_record(root, "protocols", protocol_id, record)

    def revise_notebook(self, owner_id: str, project_id: str, entry_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        root, _ = self._project(owner_id, project_id)
        entry_id = _text(entry_id)
        body = str(payload.get("body") or "").strip()
        authored_at = _text(payload.get("authored_at"))
        author = _text(payload.get("author"))
        if not entry_id or not body or not authored_at or not author:
            raise ValueError("RESEARCH_NOTEBOOK_FIELDS_REQUIRED")
        revisions_dir = root / "notebook" / entry_id / "revisions"
        prior = sorted(revisions_dir.glob("*.json")) if revisions_dir.exists() else []
        parent_revision_id = None
        revision_number = 1
        if prior:
            last = self._read(prior[-1])
            parent_revision_id = last["revision_id"]
            revision_number = int(last["revision_number"]) + 1
        content_sha = _sha(body)
        material = _stable(
            {
                "project_id": project_id,
                "entry_id": entry_id,
                "revision_number": revision_number,
                "parent_revision_id": parent_revision_id,
                "content_sha256": content_sha,
                "author": author,
                "authored_at": authored_at,
            }
        )
        revision_id = f"notebook-rev-{_sha(material)[:20]}"
        record = {
            "schema_version": RESEARCH_SCHEMA_VERSION,
            "entry_id": entry_id,
            "project_id": project_id,
            "revision_id": revision_id,
            "revision_number": revision_number,
            "parent_revision_id": parent_revision_id,
            "body": body,
            "content_sha256": content_sha,
            "author": author,
            "authored_at": authored_at,
            "immutable": True,
        }
        path = revisions_dir / f"{revision_number:06d}-{revision_id}.json"
        if path.exists():
            return {"created": False, "revision": self._read(path)}
        _atomic(path, record)
        _atomic(root / "notebook" / entry_id / "latest.json", {"revision_id": revision_id, "revision_number": revision_number})
        return {"created": True, "revision": record}

    def add_sample(self, owner_id: str, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        root, _ = self._project(owner_id, project_id)
        label = _text(payload.get("label"))
        sample_type = _text(payload.get("sample_type"))
        provenance = dict(payload.get("provenance") or {})
        if not label or not sample_type or not provenance:
            raise ValueError("RESEARCH_SAMPLE_FIELDS_REQUIRED")
        sample_id = _text(payload.get("sample_id")) or f"sample-{_sha(project_id + ':' + label)[:20]}"
        record = asdict(Sample(sample_id, project_id, sample_type, label, _text(payload.get("collected_at")) or None, provenance))
        return self._immutable_record(root, "samples", sample_id, record)

    def add_dataset(self, owner_id: str, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        root, _ = self._project(owner_id, project_id)
        title = _text(payload.get("title"))
        checksum = _text(payload.get("checksum_sha256")).casefold()
        provenance = dict(payload.get("provenance") or {})
        if not title or len(checksum) != 64 or any(ch not in "0123456789abcdef" for ch in checksum) or not provenance:
            raise ValueError("RESEARCH_DATASET_FIELDS_INVALID")
        dataset_id = _text(payload.get("dataset_id")) or f"dataset-{checksum[:20]}"
        record = asdict(Dataset(dataset_id, project_id, title, checksum, _text(payload.get("schema_ref")) or None, provenance))
        return self._immutable_record(root, "datasets", dataset_id, record)

    def attach(self, owner_id: str, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        root, _ = self._project(owner_id, project_id)
        kind = _text(payload.get("kind")).casefold()
        source_id = _text(payload.get("source_id"))
        if kind not in {"literature_run", "candidate_knowledge", "artifact_registry", "external_reference"} or not source_id:
            raise ValueError("RESEARCH_ATTACHMENT_INVALID")
        provenance: dict[str, Any] = {}
        if kind == "literature_run":
            readiness = self.literature.readiness(source_id)
            provenance = {
                "run_id": source_id,
                "source_sha256": readiness["source_sha256"],
                "extraction_sha256": readiness["extraction_sha256"],
                "evidence_span_count": readiness["evidence_span_count"],
                "ready_for_review": readiness["ready_for_review"],
            }
        elif kind == "candidate_knowledge":
            run_id = _text(payload.get("literature_run_id"))
            if not run_id:
                raise ValueError("RESEARCH_CANDIDATE_LITERATURE_RUN_REQUIRED")
            run_dir = self.literature._run_dir(run_id)
            handoffs_path = run_dir / "candidate_handoffs.json"
            handoffs = json.loads(handoffs_path.read_text(encoding="utf-8")) if handoffs_path.exists() else []
            matches = [item for item in handoffs if item.get("handoff_id") == source_id or source_id in item.get("candidate_ids", [])]
            if not matches:
                raise ValueError("RESEARCH_CANDIDATE_ARTIFACT_NOT_FOUND")
            provenance = {"literature_run_id": run_id, "candidate_handoff": matches[0]}
        elif kind == "artifact_registry":
            artifact = self.artifact_registry.require(source_id)
            provenance = {
                "artifact_id": artifact.artifact_id,
                "checksum": artifact.checksum,
                "source_uri": artifact.source_uri,
                "evidence_uris": list(artifact.evidence_uris),
            }
        else:
            uri = _text(payload.get("uri"))
            checksum = _text(payload.get("checksum_sha256")).casefold()
            if ":" not in uri or len(checksum) != 64:
                raise ValueError("RESEARCH_EXTERNAL_ATTACHMENT_PROVENANCE_REQUIRED")
            provenance = {"uri": uri, "checksum_sha256": checksum}
        material = _stable({"kind": kind, "source_id": source_id, "provenance": provenance})
        attachment_id = f"attachment-{_sha(material)[:20]}"
        record = {
            "schema_version": RESEARCH_SCHEMA_VERSION,
            "attachment_id": attachment_id,
            "project_id": project_id,
            "kind": kind,
            "source_id": source_id,
            "provenance": provenance,
            "note": _text(payload.get("note")) or None,
            "private": True,
        }
        return self._immutable_record(root, "attachments", attachment_id, record)

    def add_claim(self, owner_id: str, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        root, _ = self._project(owner_id, project_id)
        statement = _text(payload.get("statement"))
        state = _text(payload.get("state") or "needs_review").casefold()
        provenance = dict(payload.get("provenance") or {})
        confidence = payload.get("confidence")
        if not statement or state not in {"needs_review", "supported", "contested", "rejected"} or not provenance:
            raise ValueError("RESEARCH_CLAIM_FIELDS_INVALID")
        if confidence is not None and not 0 <= float(confidence) <= 1:
            raise ValueError("RESEARCH_CLAIM_CONFIDENCE_INVALID")
        claim_id = _text(payload.get("claim_id")) or f"claim-{_sha(project_id + ':' + statement)[:20]}"
        record = asdict(Claim(claim_id, project_id, statement, float(confidence) if confidence is not None else None, state, provenance))
        return self._immutable_record(root, "claims", claim_id, record)

    def add_evidence(self, owner_id: str, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        root, _ = self._project(owner_id, project_id)
        attachment_id = _text(payload.get("attachment_id"))
        claim_id = _text(payload.get("claim_id")) or None
        relation = _text(payload.get("relation")).casefold()
        if relation not in {"supports", "contradicts", "context", "method"}:
            raise ValueError("RESEARCH_EVIDENCE_RELATION_INVALID")
        self._read(root / "attachments" / f"{attachment_id}.json")
        if claim_id:
            self._read(root / "claims" / f"{claim_id}.json")
        material = _stable({"attachment_id": attachment_id, "claim_id": claim_id, "relation": relation})
        evidence_id = f"evidence-{_sha(material)[:20]}"
        record = asdict(Evidence(evidence_id, project_id, claim_id, attachment_id, relation, _text(payload.get("note")) or None))
        return self._immutable_record(root, "evidence", evidence_id, record)

    def add_decision(self, owner_id: str, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        root, _ = self._project(owner_id, project_id)
        subject_id = _text(payload.get("subject_id"))
        decision = _text(payload.get("decision")).casefold()
        rationale = _text(payload.get("rationale"))
        decided_by = _text(payload.get("decided_by"))
        decided_at = _text(payload.get("decided_at"))
        if not subject_id or decision not in DECISIONS or not rationale or not decided_by or not decided_at:
            raise ValueError("RESEARCH_DECISION_FIELDS_INVALID")
        material = _stable({"subject_id": subject_id, "decision": decision, "decided_by": decided_by, "decided_at": decided_at})
        decision_id = f"decision-{_sha(material)[:20]}"
        record = asdict(Decision(decision_id, project_id, subject_id, decision, rationale, decided_by, decided_at))
        return self._immutable_record(root, "decisions", decision_id, record)

    def upsert_task(self, owner_id: str, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        root, _ = self._project(owner_id, project_id)
        title = _text(payload.get("title"))
        task_id = _text(payload.get("task_id")) or f"task-{_sha(project_id + ':' + title)[:20]}"
        state = _text(payload.get("state") or "todo").casefold()
        blockers = [_text(item) for item in payload.get("blockers", []) if _text(item)]
        if not title or state not in TASK_STATES:
            raise ValueError("RESEARCH_TASK_FIELDS_INVALID")
        if state == "blocked" and not blockers:
            raise ValueError("RESEARCH_BLOCKED_TASK_REQUIRES_BLOCKER")
        record = {
            "schema_version": RESEARCH_SCHEMA_VERSION,
            "task_id": task_id,
            "project_id": project_id,
            "title": title,
            "state": state,
            "milestone": _text(payload.get("milestone")) or None,
            "due_at": _text(payload.get("due_at")) or None,
            "blockers": blockers,
            "updated_at": _text(payload.get("updated_at")),
        }
        if not record["updated_at"]:
            raise ValueError("RESEARCH_TASK_UPDATE_TIME_REQUIRED")
        _atomic(root / "tasks" / f"{task_id}.json", record)
        return record

    @staticmethod
    def _immutable_record(root: Path, kind: str, record_id: str, record: dict[str, Any]) -> dict[str, Any]:
        record = {"schema_version": RESEARCH_SCHEMA_VERSION, **record}
        path = root / kind / f"{record_id}.json"
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing != record:
                raise ValueError(f"RESEARCH_{kind.upper()}_IMMUTABLE_CONFLICT")
            return {"created": False, kind.rstrip("s"): existing}
        _atomic(path, record)
        return {"created": True, kind.rstrip("s"): record}

    def manifest(self, owner_id: str, project_id: str) -> dict[str, Any]:
        root, project = self._project(owner_id, project_id)
        categories = ["questions", "protocols", "samples", "datasets", "attachments", "claims", "evidence", "decisions", "tasks"]
        records: dict[str, list[dict[str, Any]]] = {}
        checksums: dict[str, str] = {}
        for category in categories:
            directory = root / category
            items = []
            if directory.exists():
                for path in sorted(directory.glob("*.json")):
                    item = self._read(path)
                    items.append(item)
                    checksums[str(path.relative_to(root))] = _sha(_stable(item))
            records[category] = items
        notebook = []
        notebook_root = root / "notebook"
        if notebook_root.exists():
            for path in sorted(notebook_root.glob("*/revisions/*.json")):
                item = self._read(path)
                notebook.append(item)
                checksums[str(path.relative_to(root))] = _sha(_stable(item))
        blockers = [task for task in records["tasks"] if task.get("state") == "blocked"]
        manifest_core = {
            "schema_version": RESEARCH_SCHEMA_VERSION,
            "project": project,
            "records": records,
            "notebook_revisions": notebook,
            "file_checksums": checksums,
            "blockers": blockers,
        }
        return {
            **manifest_core,
            "manifest_sha256": _sha(_stable(manifest_core)),
            "reproducibility_state": "blocked" if blockers else "review_ready",
            "private_by_default": True,
            "scientific_publication_authorized": False,
            "live_laboratory_control": False,
            "production_deployment_authorized": False,
            "knowledge_graph_mutation_authorized": False,
        }

    def readiness(self, owner_id: str, project_id: str) -> dict[str, Any]:
        manifest = self.manifest(owner_id, project_id)
        records = manifest["records"]
        return {
            "project_id": project_id,
            "questions": len(records["questions"]),
            "protocols": len(records["protocols"]),
            "notebook_revisions": len(manifest["notebook_revisions"]),
            "samples": len(records["samples"]),
            "datasets": len(records["datasets"]),
            "attachments": len(records["attachments"]),
            "claims": len(records["claims"]),
            "evidence": len(records["evidence"]),
            "decisions": len(records["decisions"]),
            "tasks": len(records["tasks"]),
            "blockers": manifest["blockers"],
            "reproducibility_manifest_sha256": manifest["manifest_sha256"],
            "private_by_default": True,
            "public_sharing_enabled": False,
            "scientific_publication_authorized": False,
            "live_laboratory_control": False,
            "production_deployment_authorized": False,
            "knowledge_graph_mutation_authorized": False,
            "decision": "BLOCKED" if manifest["blockers"] else "PROJECT_REVIEW_READY",
        }
