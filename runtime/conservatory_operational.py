"""Owner-scoped Conservatory operational slice for CALYX issue #451.

The service is deliberately private and review-oriented. It persists collection records,
stable QR labels, event history, and evidence-bearing media without accepting taxonomy,
exposing private location data publicly, publishing science, or mutating the Knowledge Graph.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.calyx_orchestrator.artifact_registry import (
    ArtifactRegistration,
    ImmutableArtifactRegistry,
)

CONSERVATORY_SCHEMA_VERSION = "calyx-conservatory/v1"
SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
EVENT_TYPES = {"acquisition", "repotting", "flowering", "treatment", "movement"}
IDENTITY_STATES = {"matched", "ambiguous", "unresolved"}
MEDIA_ROLES = {"plant", "flower", "tag", "roots", "habit", "other"}


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _safe(value: str, field: str) -> str:
    cleaned = _text(value)
    if not cleaned:
        raise ValueError(f"{field.upper()}_REQUIRED")
    normalized = SAFE_RE.sub("-", cleaned).strip("-.")[:120]
    if not normalized:
        raise ValueError(f"{field.upper()}_INVALID")
    return normalized


def _atomic_json(path: Path, payload: Any) -> None:
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


def _load(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def conservatory_root() -> Path:
    return Path(os.getenv("CALYX_CONSERVATORY_DIR", "/tmp/calyx/conservatory"))


@dataclass(frozen=True)
class OwnerScope:
    owner_id: str
    owner_key: str

    @classmethod
    def from_id(cls, owner_id: str) -> "OwnerScope":
        normalized = _text(owner_id)
        if not normalized:
            raise ValueError("CONSERVATORY_OWNER_REQUIRED")
        return cls(owner_id=normalized, owner_key=_sha_text(normalized.casefold())[:24])


class ConservatoryService:
    def __init__(
        self,
        workspace: Path | None = None,
        *,
        artifact_registry: ImmutableArtifactRegistry | None = None,
    ) -> None:
        self.workspace = workspace or conservatory_root()
        self.artifact_registry = artifact_registry or ImmutableArtifactRegistry()

    def _owner_root(self, owner_id: str) -> tuple[OwnerScope, Path]:
        scope = OwnerScope.from_id(owner_id)
        return scope, self.workspace / "owners" / scope.owner_key

    @staticmethod
    def _record_path(root: Path, kind: str, record_id: str) -> Path:
        return root / kind / f"{_safe(record_id, kind)}.json"

    @staticmethod
    def _require_uri(value: Any, field: str) -> str:
        text = _text(value)
        if ":" not in text:
            raise ValueError(f"{field.upper()}_INVALID")
        return text

    def create_location(self, owner_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        scope, root = self._owner_root(owner_id)
        location_id = _safe(payload.get("location_id") or payload.get("label"), "location_id")
        label = _text(payload.get("label"))
        if not label:
            raise ValueError("LOCATION_LABEL_REQUIRED")
        privacy = _text(payload.get("privacy") or "private").casefold()
        if privacy != "private":
            raise ValueError("CONSERVATORY_LOCATION_MUST_REMAIN_PRIVATE")
        record = {
            "schema_version": CONSERVATORY_SCHEMA_VERSION,
            "location_id": location_id,
            "owner_key": scope.owner_key,
            "label": label,
            "zone": _text(payload.get("zone")) or None,
            "microclimate": dict(payload.get("microclimate") or {}),
            "privacy": "private",
            "publicly_exposed": False,
        }
        path = self._record_path(root, "locations", location_id)
        if path.exists():
            existing = _load(path, {})
            if existing != record:
                raise ValueError("CONSERVATORY_LOCATION_IMMUTABLE_CONFLICT")
            return {"created": False, "location": existing}
        _atomic_json(path, record)
        return {"created": True, "location": record}

    def _location(self, root: Path, location_id: str) -> dict[str, Any]:
        path = self._record_path(root, "locations", location_id)
        if not path.exists():
            raise FileNotFoundError(f"conservatory location not found: {location_id}")
        return _load(path, {})

    def _media_records(
        self,
        *,
        scope: OwnerScope,
        plant_id: str,
        media_payloads: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        records: list[dict[str, Any]] = []
        duplicates: list[str] = []
        for index, item in enumerate(media_payloads, start=1):
            role = _text(item.get("role") or "other").casefold()
            if role not in MEDIA_ROLES:
                raise ValueError(f"CONSERVATORY_MEDIA_ROLE_INVALID:{role}")
            checksum = _text(item.get("sha256")).casefold()
            if not SHA256_RE.fullmatch(checksum):
                raise ValueError("CONSERVATORY_MEDIA_SHA256_INVALID")
            source_uri = self._require_uri(item.get("source_uri"), "media_source_uri")
            license_code = _text(item.get("license"))
            attribution = _text(item.get("attribution"))
            if not license_code or not attribution:
                raise ValueError("CONSERVATORY_MEDIA_RIGHTS_REQUIRED")
            media_id = _safe(
                item.get("media_id") or f"{plant_id}-{role}-{checksum[:12]}-{index}",
                "media_id",
            )
            record = {
                "media_id": media_id,
                "role": role,
                "sha256": checksum,
                "source_uri": source_uri,
                "license": license_code,
                "attribution": attribution,
                "captured_at": _text(item.get("captured_at")) or None,
                "owner_key": scope.owner_key,
                "plant_id": plant_id,
                "publicly_exposed": False,
            }
            artifact_id = f"conservatory-media:{scope.owner_key}:{media_id}"
            registration = self.artifact_registry.register(
                ArtifactRegistration(
                    artifact_id=artifact_id,
                    content=_stable_json(record).encode("utf-8"),
                    media_type="application/json",
                    source_uri=source_uri,
                    producer_assignment_id=f"calyx-451:{plant_id}",
                    license=license_code,
                    evidence_uris=(source_uri,),
                    metadata={"image_sha256": checksum, "role": role, "owner_key": scope.owner_key},
                )
            )
            self.artifact_registry.require_evidence(artifact_id)
            if registration.duplicate_content_of:
                duplicates.append(registration.duplicate_content_of)
            record["artifact_id"] = artifact_id
            records.append(record)
        return records, sorted(set(duplicates))

    def _existing_plants(self, root: Path) -> list[dict[str, Any]]:
        directory = root / "plants"
        if not directory.exists():
            return []
        records: list[dict[str, Any]] = []
        for path in sorted(directory.glob("*.json")):
            try:
                records.append(_load(path, {}))
            except (OSError, json.JSONDecodeError):
                continue
        return records

    @staticmethod
    def _duplicate_candidates(
        existing: list[dict[str, Any]],
        *,
        accession_number: str,
        tag_text: str | None,
        media_checksums: set[str],
    ) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        normalized_tag = _text(tag_text).casefold() if tag_text else ""
        for plant in existing:
            reasons: list[str] = []
            if _text(plant.get("accession_number")).casefold() == accession_number.casefold():
                reasons.append("same_accession_number")
            existing_tag = _text(plant.get("tag_text")).casefold()
            if normalized_tag and existing_tag and existing_tag == normalized_tag:
                reasons.append("same_tag_text")
            existing_checksums = {item.get("sha256") for item in plant.get("media", [])}
            if media_checksums & existing_checksums:
                reasons.append("same_media_checksum")
            if reasons:
                output.append({"plant_id": plant.get("plant_id"), "reasons": sorted(set(reasons))})
        return sorted(output, key=lambda item: str(item.get("plant_id")))

    def intake(self, owner_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        scope, root = self._owner_root(owner_id)
        collection = dict(payload.get("collection") or {})
        accession = dict(payload.get("accession") or {})
        plant = dict(payload.get("plant") or {})
        location = dict(payload.get("location") or {})
        media_payloads = list(payload.get("media") or [])

        collection_id = _safe(collection.get("collection_id") or collection.get("title"), "collection_id")
        collection_title = _text(collection.get("title"))
        if not collection_title:
            raise ValueError("COLLECTION_TITLE_REQUIRED")
        accession_number = _text(accession.get("accession_number"))
        if not accession_number:
            raise ValueError("ACCESSION_NUMBER_REQUIRED")
        acquired_at = _text(accession.get("acquired_at"))
        if not acquired_at:
            raise ValueError("ACCESSION_DATE_REQUIRED")

        identity_state = _text(plant.get("identity_state") or "unresolved").casefold()
        if identity_state not in IDENTITY_STATES:
            raise ValueError("CONSERVATORY_IDENTITY_STATE_INVALID")
        canonical_taxon_id = _text(plant.get("canonical_taxon_id")) or None
        scientific_name = _text(plant.get("scientific_name")) or None
        if identity_state == "matched" and not canonical_taxon_id:
            raise ValueError("CONSERVATORY_MATCHED_TAXON_ID_REQUIRED")
        display_name = _text(plant.get("display_name") or scientific_name or accession_number)
        tag_text = _text(plant.get("tag_text")) or None
        clone_name = _text(plant.get("clone_name")) or None

        plant_seed = _stable_json(
            {
                "owner_key": scope.owner_key,
                "collection_id": collection_id,
                "accession_number": accession_number,
                "clone_name": clone_name,
            }
        )
        plant_id = _safe(plant.get("plant_id") or f"plant-{_sha_text(plant_seed)[:20]}", "plant_id")
        accession_id = f"acc-{_sha_text(scope.owner_key + ':' + collection_id + ':' + accession_number)[:20]}"
        clone_id = f"clone-{_sha_text(plant_id + ':' + (clone_name or 'primary'))[:20]}"

        location_result = self.create_location(owner_id, location)
        location_record = location_result["location"]
        location_id = location_record["location_id"]

        canonical_request = {
            "collection": collection,
            "accession": accession,
            "plant": plant,
            "location": location,
            "media": media_payloads,
        }
        request_hash = _sha_text(_stable_json(canonical_request))
        external_import_id = _text(payload.get("import_id")) or request_hash
        import_key = _safe(f"import-{_sha_text(scope.owner_key + ':' + external_import_id)[:20]}", "import_id")
        import_path = self._record_path(root, "imports", import_key)
        if import_path.exists():
            previous = _load(import_path, {})
            if previous.get("request_hash") != request_hash:
                raise ValueError("CONSERVATORY_IMPORT_REPLAY_CONFLICT")
            return {"created": False, "replayed": True, **previous["receipt"]}

        existing_plants = self._existing_plants(root)
        media_checksums = {_text(item.get("sha256")).casefold() for item in media_payloads}
        duplicates = self._duplicate_candidates(
            existing_plants,
            accession_number=accession_number,
            tag_text=tag_text,
            media_checksums=media_checksums,
        )
        media_records, registry_duplicates = self._media_records(
            scope=scope,
            plant_id=plant_id,
            media_payloads=media_payloads,
        )

        collection_record = {
            "schema_version": CONSERVATORY_SCHEMA_VERSION,
            "collection_id": collection_id,
            "owner_key": scope.owner_key,
            "title": collection_title,
            "description": _text(collection.get("description")) or None,
            "private": True,
        }
        collection_path = self._record_path(root, "collections", collection_id)
        if collection_path.exists() and _load(collection_path, {}) != collection_record:
            raise ValueError("CONSERVATORY_COLLECTION_IMMUTABLE_CONFLICT")
        if not collection_path.exists():
            _atomic_json(collection_path, collection_record)

        accession_record = {
            "schema_version": CONSERVATORY_SCHEMA_VERSION,
            "accession_id": accession_id,
            "accession_number": accession_number,
            "owner_key": scope.owner_key,
            "collection_id": collection_id,
            "acquired_at": acquired_at,
            "source": _text(accession.get("source")) or None,
            "purchase_price": accession.get("purchase_price"),
            "notes": _text(accession.get("notes")) or None,
        }
        accession_path = self._record_path(root, "accessions", accession_id)
        if accession_path.exists() and _load(accession_path, {}) != accession_record:
            raise ValueError("CONSERVATORY_ACCESSION_IMMUTABLE_CONFLICT")
        if not accession_path.exists():
            _atomic_json(accession_path, accession_record)

        clone_record = {
            "schema_version": CONSERVATORY_SCHEMA_VERSION,
            "clone_id": clone_id,
            "owner_key": scope.owner_key,
            "plant_id": plant_id,
            "clone_name": clone_name,
            "origin": _text(plant.get("clone_origin")) or None,
        }
        _atomic_json(self._record_path(root, "clones", clone_id), clone_record)

        plant_record = {
            "schema_version": CONSERVATORY_SCHEMA_VERSION,
            "plant_id": plant_id,
            "owner_key": scope.owner_key,
            "collection_id": collection_id,
            "accession_id": accession_id,
            "accession_number": accession_number,
            "clone_id": clone_id,
            "display_name": display_name,
            "scientific_name": scientific_name,
            "canonical_taxon_id": canonical_taxon_id,
            "identity_state": identity_state,
            "identity_review_required": identity_state != "matched",
            "tag_text": tag_text,
            "current_location_id": location_id,
            "media": media_records,
            "duplicate_candidates": duplicates,
            "duplicate_review_required": bool(duplicates or registry_duplicates),
            "artifact_duplicate_candidates": registry_duplicates,
            "taxonomy_acceptance_authorized": False,
            "knowledge_graph_mutation_authorized": False,
            "publicly_exposed": False,
        }
        plant_path = self._record_path(root, "plants", plant_id)
        if plant_path.exists():
            raise ValueError("CONSERVATORY_PLANT_ALREADY_EXISTS")
        _atomic_json(plant_path, plant_record)

        label_id = f"label-{_sha_text(scope.owner_key + ':' + plant_id + ':v1')[:20]}"
        qr_target = f"/brain/mission-control/conservatory/scan/{label_id}"
        label_record = {
            "schema_version": CONSERVATORY_SCHEMA_VERSION,
            "label_id": label_id,
            "owner_key": scope.owner_key,
            "plant_id": plant_id,
            "version": 1,
            "qr_target": qr_target,
            "qr_payload": qr_target,
            "printable": {
                "primary_text": display_name,
                "secondary_text": accession_number,
                "clone_text": clone_name,
                "qr_target": qr_target,
            },
            "publicly_exposed": False,
        }
        _atomic_json(self._record_path(root, "labels", label_id), label_record)

        acquisition_event = self.add_event(
            owner_id,
            plant_id,
            event_type="acquisition",
            occurred_at=acquired_at,
            details={"source": accession_record["source"], "accession_number": accession_number},
        )
        receipt = {
            "plant_id": plant_id,
            "accession_id": accession_id,
            "clone_id": clone_id,
            "collection_id": collection_id,
            "location_id": location_id,
            "label": label_record,
            "acquisition_event_id": acquisition_event["event"]["event_id"],
            "identity_state": identity_state,
            "identity_review_required": identity_state != "matched",
            "duplicate_candidates": duplicates,
            "duplicate_review_required": bool(duplicates or registry_duplicates),
            "private_collection": True,
            "public_location_exposure": False,
            "taxonomy_acceptance_authorized": False,
            "knowledge_graph_mutation_authorized": False,
        }
        _atomic_json(import_path, {"request_hash": request_hash, "receipt": receipt})
        return {"created": True, "replayed": False, **receipt}

    def _plant(self, root: Path, plant_id: str) -> dict[str, Any]:
        path = self._record_path(root, "plants", plant_id)
        if not path.exists():
            raise FileNotFoundError(f"conservatory plant not found: {plant_id}")
        return _load(path, {})

    def add_event(
        self,
        owner_id: str,
        plant_id: str,
        *,
        event_type: str,
        occurred_at: str,
        details: dict[str, Any] | None = None,
        location_id: str | None = None,
    ) -> dict[str, Any]:
        scope, root = self._owner_root(owner_id)
        plant = self._plant(root, plant_id)
        normalized_type = _text(event_type).casefold()
        if normalized_type not in EVENT_TYPES:
            raise ValueError("CONSERVATORY_EVENT_TYPE_INVALID")
        occurred = _text(occurred_at)
        if not occurred:
            raise ValueError("CONSERVATORY_EVENT_TIME_REQUIRED")
        detail_payload = dict(details or {})
        if normalized_type == "movement":
            target = _text(location_id)
            if not target:
                raise ValueError("CONSERVATORY_MOVEMENT_LOCATION_REQUIRED")
            self._location(root, target)
            detail_payload = {
                **detail_payload,
                "from_location_id": plant.get("current_location_id"),
                "to_location_id": target,
            }
        event_material = _stable_json(
            {
                "owner_key": scope.owner_key,
                "plant_id": plant_id,
                "event_type": normalized_type,
                "occurred_at": occurred,
                "details": detail_payload,
            }
        )
        event_id = f"event-{_sha_text(event_material)[:20]}"
        event = {
            "schema_version": CONSERVATORY_SCHEMA_VERSION,
            "event_id": event_id,
            "owner_key": scope.owner_key,
            "plant_id": plant_id,
            "event_type": normalized_type,
            "occurred_at": occurred,
            "details": detail_payload,
            "private": True,
        }
        path = self._record_path(root / "plant-events" / _safe(plant_id, "plant_id"), "events", event_id)
        if path.exists():
            existing = _load(path, {})
            if existing != event:
                raise ValueError("CONSERVATORY_EVENT_IMMUTABLE_CONFLICT")
            return {"created": False, "event": existing}
        _atomic_json(path, event)
        if normalized_type == "movement":
            plant["current_location_id"] = detail_payload["to_location_id"]
            _atomic_json(self._record_path(root, "plants", plant_id), plant)
        return {"created": True, "event": event}

    def events(self, owner_id: str, plant_id: str) -> list[dict[str, Any]]:
        _, root = self._owner_root(owner_id)
        self._plant(root, plant_id)
        directory = root / "plant-events" / _safe(plant_id, "plant_id") / "events"
        if not directory.exists():
            return []
        records = [_load(path, {}) for path in sorted(directory.glob("*.json"))]
        return sorted(records, key=lambda item: (str(item.get("occurred_at")), str(item.get("event_id"))))

    def dossier(self, owner_id: str, plant_id: str) -> dict[str, Any]:
        _, root = self._owner_root(owner_id)
        plant = self._plant(root, plant_id)
        accession = _load(self._record_path(root, "accessions", plant["accession_id"]), {})
        clone = _load(self._record_path(root, "clones", plant["clone_id"]), {})
        collection = _load(self._record_path(root, "collections", plant["collection_id"]), {})
        location = self._location(root, plant["current_location_id"])
        labels = []
        label_dir = root / "labels"
        if label_dir.exists():
            for path in sorted(label_dir.glob("*.json")):
                label = _load(path, {})
                if label.get("plant_id") == plant_id:
                    labels.append(label)
        return {
            "schema_version": CONSERVATORY_SCHEMA_VERSION,
            "plant": plant,
            "accession": accession,
            "clone": clone,
            "collection": collection,
            "current_location": location,
            "events": self.events(owner_id, plant_id),
            "labels": labels,
            "private_collection": True,
            "public_location_exposure": False,
            "taxonomy_acceptance_authorized": False,
            "knowledge_graph_mutation_authorized": False,
        }

    def scan(self, owner_id: str, label_id: str) -> dict[str, Any]:
        _, root = self._owner_root(owner_id)
        path = self._record_path(root, "labels", label_id)
        if not path.exists():
            raise FileNotFoundError(f"conservatory label not found: {label_id}")
        label = _load(path, {})
        return self.dossier(owner_id, label["plant_id"])

    def printable_label(self, owner_id: str, label_id: str) -> dict[str, Any]:
        _, root = self._owner_root(owner_id)
        path = self._record_path(root, "labels", label_id)
        if not path.exists():
            raise FileNotFoundError(f"conservatory label not found: {label_id}")
        label = _load(path, {})
        return {
            "label_id": label["label_id"],
            "plant_id": label["plant_id"],
            "version": label["version"],
            "qr_target": label["qr_target"],
            "qr_payload": label["qr_payload"],
            "printable": label["printable"],
            "private": True,
        }

    def readiness(self, owner_id: str) -> dict[str, Any]:
        scope, root = self._owner_root(owner_id)

        def count(kind: str) -> int:
            directory = root / kind
            return len(list(directory.glob("*.json"))) if directory.exists() else 0

        return {
            "schema_version": CONSERVATORY_SCHEMA_VERSION,
            "owner_key": scope.owner_key,
            "collections": count("collections"),
            "accessions": count("accessions"),
            "plants": count("plants"),
            "clones": count("clones"),
            "locations": count("locations"),
            "labels": count("labels"),
            "private_collection": True,
            "public_location_exposure": False,
            "autonomous_taxonomic_acceptance": False,
            "production_deployment_authorized": False,
            "knowledge_graph_mutation_authorized": False,
            "decision": "PRIVATE_OPERATIONAL_REVIEW_READY",
        }
