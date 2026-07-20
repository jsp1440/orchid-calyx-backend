from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Any

from .extractor import extract_candidates
from .models import EvidenceInput
from .repository import MemoryCandidateRepository, now


def digest(value: Any) -> str:
    payload = value if isinstance(value, str) else json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def normalize(value: str) -> str:
    return " ".join(value.casefold().split())


class CandidateExtractionService:
    def __init__(self, repository: MemoryCandidateRepository, extractor_version: str = "086a-1", ruleset_version: str = "086a-rules-1") -> None:
        self.repo = repository
        self.extractor_version = extractor_version
        self.ruleset_version = ruleset_version

    def preview(self, evidence: list[EvidenceInput], configuration: dict[str, Any] | None = None) -> dict[str, Any]:
        if not evidence:
            raise ValueError("EVIDENCE_REQUIRED")
        run_id = self.repo.create_run(digest(configuration or {}), self.extractor_version, self.ruleset_version)
        counts: dict[str, int] = {}
        for source in evidence:
            fingerprint = digest({"source_object_type": source.source_object_type, "source_object_id": source.source_object_id, "revision_id": source.revision_id, "extraction_run_id": source.extraction_run_id, "text": source.text, "anchors": [asdict(x) for x in source.source_anchors], "metadata": source.metadata, "extractor": self.extractor_version, "rules": self.ruleset_version})
            action = "REUSE" if self.repo.candidate_for_fingerprint(fingerprint) else "EXTRACT"
            self.repo.add_item(run_id, source, fingerprint, action)
            counts[action] = counts.get(action, 0) + 1
        self.repo.transition(run_id, "PLANNED")
        return {"candidate_run_id": run_id, "state": "PLANNED", "counts": counts, "candidates_created": 0, "published_nodes": 0, "published_edges": 0}

    def execute(self, run_id: int) -> dict[str, Any]:
        self.repo.transition(run_id, "EXTRACTING")
        for item in self.repo.pending(run_id):
            if run_id in self.repo.cancelled:
                return self.repo.transition(run_id, "CANCELLED")
            try:
                was_failed = item["state"] == "FAILED"
                if item["action"] == "REUSE":
                    item["state"] = "REUSED"
                    self.repo.runs[run_id]["metrics"]["reused"] += 1
                else:
                    self._extract_item(run_id, item)
                if was_failed:
                    self.repo.runs[run_id]["metrics"]["failed"] = max(0, self.repo.runs[run_id]["metrics"]["failed"] - 1)
                self.repo.runs[run_id]["last_completed_item_id"] = item["item_id"]
            except Exception as exc:
                item.update(state="FAILED", failure={"code": type(exc).__name__, "message": str(exc)})
                self.repo.runs[run_id]["metrics"]["failed"] += 1
                self.repo.open_review(run_id, None, "EXTRACTION_FAILURE", "HIGH", item["failure"])
        state = "PARTIAL" if self.repo.runs[run_id]["metrics"]["failed"] else "COMPLETED"
        return self.repo.transition(run_id, state)

    def _extract_item(self, run_id: int, item: dict[str, Any]) -> None:
        evidence: EvidenceInput = item["evidence"]
        facts = extract_candidates(evidence)
        if not facts:
            self.repo.open_review(run_id, None, "NO_CANDIDATES_EXTRACTED", "LOW", {"source_object_type": evidence.source_object_type, "source_object_id": evidence.source_object_id})
            item["state"] = "COMPLETED"
            return
        for fact in facts:
            subject = normalize(fact.subject)
            value = normalize(fact.object_value) if fact.object_value is not None else str(fact.numeric_value)
            exact_hash = digest({"kind": fact.kind.value, "subject": subject, "predicate": fact.predicate, "value": value, "unit": fact.unit, "qualifiers": fact.qualifiers})
            exact = next((x for x in self.repo.candidates if x["candidate_hash"] == exact_hash), None)
            if exact:
                group = next((g for g in self.repo.duplicate_groups.values() if exact["candidate_id"] in g["candidate_ids"]), None)
                if group is None:
                    group_id = self.repo.next_id()
                    group = {"duplicate_group_id": group_id, "candidate_ids": [exact["candidate_id"]], "state": "OPEN", "created_at": now()}
                    self.repo.duplicate_groups[group_id] = group
                self.repo.runs[run_id]["metrics"]["duplicates"] += 1
                quote = self._authorized_quote(evidence)
                existing_anchor_ids = {x["anchor"]["anchor_id"] for x in self.repo.evidence_links if x["candidate_id"] == exact["candidate_id"]}
                for anchor in evidence.source_anchors:
                    if anchor.anchor_id not in existing_anchor_ids:
                        self.repo.evidence_links.append({"evidence_link_id": self.repo.next_id(), "candidate_id": exact["candidate_id"], "revision_id": evidence.revision_id, "extraction_run_id": evidence.extraction_run_id, "source_object_type": evidence.source_object_type, "source_object_id": evidence.source_object_id, "anchor": asdict(anchor), "authorized_quote": quote, "display_policy": evidence.display_policy, "created_at": now()})
                self.repo.open_review(run_id, exact["candidate_id"], "POSSIBLE_DUPLICATE", "MEDIUM", {"duplicate_group_id": group["duplicate_group_id"], "new_evidence_fingerprint": item["fingerprint"]})
                continue
            active = self.repo.active_identity(fact.kind.value, subject, fact.predicate)
            version = 1 + max((x["version"] for x in active), default=0)
            candidate_id = self.repo.next_id()
            candidate = {"candidate_id": candidate_id, "candidate_run_id": run_id, "kind": fact.kind.value, "normalized_subject": subject, "predicate": fact.predicate, "object_value": fact.object_value, "numeric_value": fact.numeric_value, "unit": fact.unit, "qualifiers": dict(fact.qualifiers), "confidence": fact.confidence, "confidence_components": {"extraction": fact.confidence, "source": evidence.metadata.get("source_confidence", 0.5), "anchor": min((a.locator.get("confidence", 1.0) for a in evidence.source_anchors), default=1.0)}, "extraction_method": fact.method, "extractor_version": self.extractor_version, "ruleset_version": self.ruleset_version, "candidate_hash": exact_hash, "evidence_fingerprint": item["fingerprint"], "version": version, "active": True, "review_state": "REQUIRED", "published": False, "created_at": now()}
            for previous in active:
                previous["active"] = False
                previous["superseded_by_candidate_id"] = candidate_id
            self.repo.candidates.append(candidate)
            quote = self._authorized_quote(evidence)
            for anchor in evidence.source_anchors:
                self.repo.evidence_links.append({"evidence_link_id": self.repo.next_id(), "candidate_id": candidate_id, "revision_id": evidence.revision_id, "extraction_run_id": evidence.extraction_run_id, "source_object_type": evidence.source_object_type, "source_object_id": evidence.source_object_id, "anchor": asdict(anchor), "authorized_quote": quote, "display_policy": evidence.display_policy, "created_at": now()})
            self.repo.open_review(run_id, candidate_id, "CANDIDATE_REQUIRES_HUMAN_REVIEW", "MEDIUM", {"candidate_hash": exact_hash, "anchor_ids": [x.anchor_id for x in evidence.source_anchors]})
            self.repo.runs[run_id]["metrics"]["created"] += 1
            conflicts = [x for x in active if normalize(str(x.get("object_value") if x.get("object_value") is not None else x.get("numeric_value"))) != value]
            if conflicts:
                conflict_id = self.repo.next_id()
                self.repo.conflicts[conflict_id] = {"conflict_id": conflict_id, "candidate_ids": [x["candidate_id"] for x in conflicts] + [candidate_id], "state": "OPEN", "created_at": now()}
                self.repo.open_review(run_id, candidate_id, "CONFLICTING_CANDIDATES", "HIGH", {"conflict_id": conflict_id})
                self.repo.runs[run_id]["metrics"]["conflicts"] += 1
        item["state"] = "COMPLETED"

    @staticmethod
    def _authorized_quote(evidence: EvidenceInput) -> str | None:
        if evidence.display_policy == "FULL_TEXT_ALLOWED":
            return evidence.text
        if evidence.display_policy == "LIMITED_PREVIEW_ONLY":
            return evidence.text[: max(0, int(evidence.metadata.get("excerpt_limit", 160)))]
        if evidence.display_policy == "INTERNAL_RESEARCH_ONLY" and evidence.internal_use_permission:
            return evidence.text
        return None

    def cancel(self, run_id: int) -> dict[str, Any]:
        return self.repo.request_cancel(run_id)

    def resume(self, run_id: int) -> dict[str, Any]:
        self.repo.clear_cancel(run_id)
        return self.execute(run_id)
