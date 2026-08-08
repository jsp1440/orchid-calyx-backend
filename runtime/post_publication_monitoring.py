"""Governed post-publication evidence monitoring for CALYX issue #468.

The service links a published assertion to immutable ledger/evidence/source hashes,
compares later caller-supplied observations, and creates idempotent human review tasks.
It never republishes, rewrites the graph, approves science, or acquires evidence itself.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "calyx-post-publication-monitoring/v1"
EVIDENCE_STATES = {"active", "superseded", "withdrawn", "retracted"}
REVIEW_REASONS = {
    "evidence_hash_changed",
    "source_hash_changed",
    "evidence_superseded",
    "evidence_withdrawn",
    "evidence_retracted",
    "approval_stale",
    "confidence_changed",
}


def monitoring_root() -> Path:
    return Path(os.environ.get("CALYX_POST_PUBLICATION_MONITORING_WORKSPACE", "/tmp/calyx/post-publication-monitoring"))


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_time(value: object, *, code: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError(code)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(code) from exc
    if parsed.tzinfo is None:
        raise ValueError(code)
    return parsed.astimezone(UTC)


def _text(value: object) -> str:
    return str(value or "").strip()


def _stable(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(payload: Any) -> str:
    return hashlib.sha256(_stable(payload).encode("utf-8")).hexdigest()


def _owner_key(owner_id: str) -> str:
    owner = _text(owner_id)
    if not owner:
        raise ValueError("MONITOR_OWNER_REQUIRED")
    return hashlib.sha256(owner.casefold().encode()).hexdigest()[:20]


class PostPublicationMonitoringService:
    """File-backed immutable publication baselines with append-only observation history."""

    def __init__(self, workspace: Path | None = None, *, clock: callable | None = None) -> None:
        self.workspace = workspace or monitoring_root()
        self.clock = clock or _now

    def _root(self, owner_id: str) -> Path:
        root = self.workspace / "owners" / _owner_key(owner_id)
        root.mkdir(parents=True, exist_ok=True)
        return root

    @staticmethod
    def _write(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")
        return payload

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(path.stem)
        return json.loads(path.read_text(encoding="utf-8"))

    def register_publication(self, owner_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        publication_id = _text(payload.get("publication_id"))
        assertion_id = _text(payload.get("assertion_id"))
        ledger_id = _text(payload.get("ledger_id"))
        ledger_revision_id = _text(payload.get("ledger_revision_id"))
        ledger_hash = _text(payload.get("ledger_hash"))
        published_at = _parse_time(payload.get("published_at"), code="MONITOR_PUBLISHED_AT_REQUIRED")
        approved_at = _parse_time(payload.get("approved_at"), code="MONITOR_APPROVED_AT_REQUIRED")
        if not all((publication_id, assertion_id, ledger_id, ledger_revision_id, ledger_hash)):
            raise ValueError("MONITOR_PUBLICATION_IDENTITY_REQUIRED")
        if approved_at > published_at:
            raise ValueError("MONITOR_APPROVAL_AFTER_PUBLICATION")
        approval_ttl_days = int(payload.get("approval_ttl_days", 365))
        if approval_ttl_days < 1 or approval_ttl_days > 3650:
            raise ValueError("MONITOR_APPROVAL_TTL_INVALID")
        confidence = float(payload.get("confidence", -1))
        if not 0 <= confidence <= 1:
            raise ValueError("MONITOR_CONFIDENCE_INVALID")
        evidence_input = list(payload.get("evidence") or [])
        if not evidence_input:
            raise ValueError("MONITOR_EVIDENCE_REQUIRED")
        evidence: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in evidence_input:
            if not isinstance(item, dict):
                raise TypeError("MONITOR_EVIDENCE_INVALID")
            evidence_id = _text(item.get("evidence_id"))
            source_id = _text(item.get("source_id"))
            evidence_hash = _text(item.get("evidence_hash"))
            source_hash = _text(item.get("source_hash"))
            if not all((evidence_id, source_id, evidence_hash, source_hash)):
                raise ValueError("MONITOR_EVIDENCE_IDENTITY_REQUIRED")
            if evidence_id in seen:
                raise ValueError("MONITOR_DUPLICATE_EVIDENCE_ID")
            seen.add(evidence_id)
            evidence.append(
                {
                    "evidence_id": evidence_id,
                    "source_id": source_id,
                    "evidence_hash": evidence_hash,
                    "source_hash": source_hash,
                    "source_uri": _text(item.get("source_uri")) or None,
                    "state": "active",
                }
            )
        evidence.sort(key=lambda item: item["evidence_id"])
        record = {
            "schema_version": SCHEMA_VERSION,
            "publication_id": publication_id,
            "assertion_id": assertion_id,
            "ledger_id": ledger_id,
            "ledger_revision_id": ledger_revision_id,
            "ledger_hash": ledger_hash,
            "published_at": _iso(published_at),
            "approved_at": _iso(approved_at),
            "approval_ttl_days": approval_ttl_days,
            "confidence": confidence,
            "evidence": evidence,
            "provenance": list(payload.get("provenance") or []),
            "historical_record_preserved": True,
            "automatic_republication_authorized": False,
            "production_graph_rewrite_authorized": False,
            "scientific_approval_authorized": False,
            "production_deployment_authorized": False,
        }
        record["publication_digest"] = _digest(record)
        path = self._root(owner_id) / "publications" / f"{publication_id}.json"
        if path.exists():
            existing = self._read(path)
            if existing.get("publication_digest") == record["publication_digest"]:
                return existing
            raise RuntimeError("MONITOR_IMMUTABLE_PUBLICATION_CONFLICT")
        self._write(path, record)
        self._write(self._root(owner_id) / "observations" / f"{publication_id}.json", {"schema_version": SCHEMA_VERSION, "observations": []})
        return record

    def get_publication(self, owner_id: str, publication_id: str) -> dict[str, Any]:
        return self._read(self._root(owner_id) / "publications" / f"{publication_id}.json")

    def _task_id(self, publication_id: str, reason: str, evidence_id: str | None, fingerprint: str) -> str:
        material = {"publication_id": publication_id, "reason": reason, "evidence_id": evidence_id, "fingerprint": fingerprint}
        return f"review-{_digest(material)[:24]}"

    def _create_task(
        self,
        owner_id: str,
        publication: dict[str, Any],
        *,
        reason: str,
        evidence_id: str | None,
        fingerprint: str,
        detail: dict[str, Any],
        observed_at: str,
    ) -> dict[str, Any]:
        if reason not in REVIEW_REASONS:
            raise ValueError("MONITOR_REVIEW_REASON_INVALID")
        task_id = self._task_id(publication["publication_id"], reason, evidence_id, fingerprint)
        path = self._root(owner_id) / "tasks" / f"{task_id}.json"
        if path.exists():
            return self._read(path)
        task = {
            "schema_version": SCHEMA_VERSION,
            "task_id": task_id,
            "publication_id": publication["publication_id"],
            "assertion_id": publication["assertion_id"],
            "ledger_id": publication["ledger_id"],
            "ledger_revision_id": publication["ledger_revision_id"],
            "ledger_hash": publication["ledger_hash"],
            "reason": reason,
            "evidence_id": evidence_id,
            "detail": detail,
            "observed_at": observed_at,
            "status": "review_required",
            "automatic_republication_authorized": False,
            "production_graph_rewrite_authorized": False,
            "scientific_approval_authorized": False,
        }
        task["task_digest"] = _digest(task)
        return self._write(path, task)

    def observe(self, owner_id: str, publication_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        publication = self.get_publication(owner_id, publication_id)
        observed = _parse_time(payload.get("observed_at"), code="MONITOR_OBSERVED_AT_REQUIRED")
        observed_at = _iso(observed)
        current_confidence = float(payload.get("confidence", publication["confidence"]))
        if not 0 <= current_confidence <= 1:
            raise ValueError("MONITOR_CONFIDENCE_INVALID")
        supplied = list(payload.get("evidence") or [])
        by_id = {item["evidence_id"]: item for item in publication["evidence"]}
        observations: list[dict[str, Any]] = []
        tasks: list[dict[str, Any]] = []
        for item in supplied:
            if not isinstance(item, dict):
                raise TypeError("MONITOR_EVIDENCE_OBSERVATION_INVALID")
            evidence_id = _text(item.get("evidence_id"))
            if evidence_id not in by_id:
                raise ValueError(f"MONITOR_UNKNOWN_EVIDENCE_ID:{evidence_id}")
            baseline = by_id[evidence_id]
            state = _text(item.get("state")) or "active"
            if state not in EVIDENCE_STATES:
                raise ValueError("MONITOR_EVIDENCE_STATE_INVALID")
            evidence_hash = _text(item.get("evidence_hash")) or baseline["evidence_hash"]
            source_hash = _text(item.get("source_hash")) or baseline["source_hash"]
            current = {
                "evidence_id": evidence_id,
                "state": state,
                "evidence_hash": evidence_hash,
                "source_hash": source_hash,
            }
            observations.append(current)
            if evidence_hash != baseline["evidence_hash"]:
                tasks.append(self._create_task(owner_id, publication, reason="evidence_hash_changed", evidence_id=evidence_id, fingerprint=evidence_hash, detail={"baseline": baseline["evidence_hash"], "observed": evidence_hash}, observed_at=observed_at))
            if source_hash != baseline["source_hash"]:
                tasks.append(self._create_task(owner_id, publication, reason="source_hash_changed", evidence_id=evidence_id, fingerprint=source_hash, detail={"baseline": baseline["source_hash"], "observed": source_hash}, observed_at=observed_at))
            state_reason = {
                "superseded": "evidence_superseded",
                "withdrawn": "evidence_withdrawn",
                "retracted": "evidence_retracted",
            }.get(state)
            if state_reason:
                tasks.append(self._create_task(owner_id, publication, reason=state_reason, evidence_id=evidence_id, fingerprint=state, detail={"state": state}, observed_at=observed_at))

        expiry = _parse_time(publication["approved_at"], code="MONITOR_APPROVED_AT_REQUIRED") + timedelta(days=int(publication["approval_ttl_days"]))
        if observed > expiry:
            tasks.append(self._create_task(owner_id, publication, reason="approval_stale", evidence_id=None, fingerprint=_iso(expiry), detail={"approval_expires_at": _iso(expiry)}, observed_at=observed_at))
        if current_confidence != float(publication["confidence"]):
            tasks.append(self._create_task(owner_id, publication, reason="confidence_changed", evidence_id=None, fingerprint=f"{current_confidence:.12g}", detail={"baseline": publication["confidence"], "observed": current_confidence}, observed_at=observed_at))

        observation = {
            "schema_version": SCHEMA_VERSION,
            "observation_id": f"obs-{_digest({'publication_id': publication_id, 'observed_at': observed_at, 'evidence': observations, 'confidence': current_confidence})[:24]}",
            "publication_id": publication_id,
            "observed_at": observed_at,
            "evidence": observations,
            "confidence": current_confidence,
            "review_task_ids": sorted({task["task_id"] for task in tasks}),
            "historical_record_preserved": True,
            "automatic_republication_performed": False,
            "production_graph_rewrite_performed": False,
            "scientific_approval_performed": False,
        }
        history_path = self._root(owner_id) / "observations" / f"{publication_id}.json"
        history = self._read(history_path)
        if not any(item["observation_id"] == observation["observation_id"] for item in history["observations"]):
            history["observations"].append(observation)
            history["observations"].sort(key=lambda item: (item["observed_at"], item["observation_id"]))
            self._write(history_path, history)
        return {**observation, "review_tasks": sorted(tasks, key=lambda item: item["task_id"])}

    def review_tasks(self, owner_id: str, publication_id: str | None = None) -> dict[str, Any]:
        directory = self._root(owner_id) / "tasks"
        tasks = [self._read(path) for path in sorted(directory.glob("*.json"))] if directory.exists() else []
        if publication_id:
            tasks = [item for item in tasks if item["publication_id"] == publication_id]
        return {"schema_version": SCHEMA_VERSION, "count": len(tasks), "tasks": tasks}

    def status(self, owner_id: str, publication_id: str, *, as_of: datetime | None = None) -> dict[str, Any]:
        publication = self.get_publication(owner_id, publication_id)
        now = (as_of or self.clock()).astimezone(UTC)
        history = self._read(self._root(owner_id) / "observations" / f"{publication_id}.json")["observations"]
        last = max((_parse_time(item["observed_at"], code="MONITOR_OBSERVED_AT_REQUIRED") for item in history), default=None)
        reference = last or _parse_time(publication["published_at"], code="MONITOR_PUBLISHED_AT_REQUIRED")
        lag_seconds = max(0.0, (now - reference).total_seconds())
        tasks = self.review_tasks(owner_id, publication_id)["tasks"]
        return {
            "schema_version": SCHEMA_VERSION,
            "publication_id": publication_id,
            "assertion_id": publication["assertion_id"],
            "ledger_id": publication["ledger_id"],
            "monitoring_lag_seconds": round(lag_seconds, 3),
            "last_observed_at": _iso(last) if last else None,
            "observation_count": len(history),
            "review_task_count": len(tasks),
            "decision": "REVIEW_REQUIRED" if tasks else "MONITORING_CURRENT_NO_CHANGE",
            "historical_record_preserved": True,
            "automatic_republication_authorized": False,
            "production_graph_rewrite_authorized": False,
            "scientific_approval_authorized": False,
            "production_deployment_authorized": False,
        }
