"""Governed homepage audit, redesign, validation, and release eligibility for CALYX #471.

The pipeline persists versioned audit/specification/implementation/validation evidence,
checks canonical species-dossier references when supplied, and fails closed unless
visual, accessibility, scientific, taxonomy, media, evidence, and specification gates
all pass. It never deploys or activates a homepage.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from runtime.species_dossier import SpeciesDossierService

SCHEMA_VERSION = "calyx-homepage-governance/v1"
AUDIT_SCHEMA = "HomepageAuditV1"
SPEC_SCHEMA = "HomepageRedesignSpecificationV1"
STATES = {
    "draft",
    "owner_review",
    "approved_for_implementation",
    "implementation_received",
    "validation_failed",
    "validated",
    "release_eligible",
}


def homepage_root() -> Path:
    return Path(os.environ.get("CALYX_HOMEPAGE_WORKSPACE", "/tmp/calyx/homepage"))


def _text(value: object) -> str:
    return str(value or "").strip()


def _stable(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(payload: Any) -> str:
    return hashlib.sha256(_stable(payload).encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _owner_key(owner_id: str) -> str:
    owner = _text(owner_id)
    if not owner:
        raise ValueError("HOMEPAGE_OWNER_REQUIRED")
    return hashlib.sha256(owner.casefold().encode()).hexdigest()[:20]


def _screenshot(item: dict[str, Any]) -> dict[str, Any]:
    required = {key: _text(item.get(key)) for key in ("artifact_id", "checksum", "source_uri", "captured_at")}
    if not all(required.values()):
        raise ValueError("HOMEPAGE_SCREENSHOT_PROVENANCE_REQUIRED")
    return {**required, "viewport": item.get("viewport") or {}, "route": _text(item.get("route")) or "/"}


def _versioned_id(kind: str, logical_id: str, version: int, payload: dict[str, Any]) -> str:
    return f"{kind}-{logical_id}-v{version}-{_digest(payload)[:12]}"


class HomepageGovernanceService:
    def __init__(self, workspace: Path | None = None, *, dossiers: SpeciesDossierService | None = None) -> None:
        self.workspace = workspace or homepage_root()
        self.dossiers = dossiers or SpeciesDossierService()

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

    def _next_version(self, owner_id: str, kind: str, logical_id: str) -> int:
        directory = self._root(owner_id) / kind / logical_id
        if not directory.exists():
            return 1
        versions = [int(path.stem.removeprefix("v")) for path in directory.glob("v*.json") if path.stem.removeprefix("v").isdigit()]
        return max(versions, default=0) + 1

    def submit_audit(self, owner_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        audit_id = _text(payload.get("audit_id"))
        deployed_revision = _text(payload.get("deployed_revision"))
        if not audit_id or not deployed_revision:
            raise ValueError("HOMEPAGE_AUDIT_IDENTITY_REQUIRED")
        screenshots_raw = list(payload.get("source_screenshots") or [])
        if not screenshots_raw:
            raise ValueError("HOMEPAGE_SOURCE_SCREENSHOTS_REQUIRED")
        screenshots = [_screenshot(dict(item)) for item in screenshots_raw]
        route_inventory = sorted({_text(item) for item in payload.get("route_inventory", []) if _text(item)})
        findings = list(payload.get("findings") or [])
        evidence_anchors = list(payload.get("evidence_anchors") or [])
        provenance = list(payload.get("provenance") or [])
        if not provenance:
            raise ValueError("HOMEPAGE_AUDIT_PROVENANCE_REQUIRED")
        version = self._next_version(owner_id, "audits", audit_id)
        record = {
            "schema_version": SCHEMA_VERSION,
            "document_schema": AUDIT_SCHEMA,
            "audit_id": audit_id,
            "version": version,
            "deployed_revision": deployed_revision,
            "source_screenshots": screenshots,
            "route_inventory": route_inventory,
            "findings": findings,
            "evidence_anchors": evidence_anchors,
            "provenance": provenance,
            "state": "owner_review",
            "created_at": _now(),
            "automatic_deployment_authorized": False,
            "scientific_publication_authorized": False,
        }
        record["record_id"] = _versioned_id("audit", audit_id, version, record)
        record["checksum"] = _digest(record)
        return self._write(self._root(owner_id) / "audits" / audit_id / f"v{version}.json", record)

    def get_audit(self, owner_id: str, audit_id: str, version: int | None = None) -> dict[str, Any]:
        directory = self._root(owner_id) / "audits" / audit_id
        if version is None:
            paths = sorted(directory.glob("v*.json"), key=lambda p: int(p.stem[1:])) if directory.exists() else []
            if not paths:
                raise FileNotFoundError(audit_id)
            return self._read(paths[-1])
        return self._read(directory / f"v{version}.json")

    def submit_specification(self, owner_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        specification_id = _text(payload.get("specification_id"))
        audit_id = _text(payload.get("audit_id"))
        audit_version = int(payload.get("audit_version", 0))
        if not specification_id or not audit_id or audit_version < 1:
            raise ValueError("HOMEPAGE_SPEC_IDENTITY_REQUIRED")
        audit = self.get_audit(owner_id, audit_id, audit_version)
        required_sections = sorted({_text(item) for item in payload.get("required_sections", []) if _text(item)})
        required_routes = sorted({_text(item) for item in payload.get("required_routes", []) if _text(item)})
        required_components = sorted({_text(item) for item in payload.get("required_components", []) if _text(item)})
        if not required_sections:
            raise ValueError("HOMEPAGE_SPEC_SECTIONS_REQUIRED")
        scientific_rules = list(payload.get("scientific_wording_rules") or [])
        accessibility_requirements = list(payload.get("accessibility_requirements") or [])
        visual_requirements = list(payload.get("visual_requirements") or [])
        evidence_anchors = list(payload.get("evidence_anchors") or [])
        provenance = list(payload.get("provenance") or [])
        if not provenance:
            raise ValueError("HOMEPAGE_SPEC_PROVENANCE_REQUIRED")
        version = self._next_version(owner_id, "specifications", specification_id)
        record = {
            "schema_version": SCHEMA_VERSION,
            "document_schema": SPEC_SCHEMA,
            "specification_id": specification_id,
            "version": version,
            "audit_ref": {"audit_id": audit_id, "version": audit_version, "checksum": audit["checksum"]},
            "required_sections": required_sections,
            "required_routes": required_routes,
            "required_components": required_components,
            "scientific_wording_rules": scientific_rules,
            "accessibility_requirements": accessibility_requirements,
            "visual_requirements": visual_requirements,
            "taxonomy_requirements": list(payload.get("taxonomy_requirements") or []),
            "media_requirements": list(payload.get("media_requirements") or []),
            "evidence_requirements": list(payload.get("evidence_requirements") or []),
            "evidence_anchors": evidence_anchors,
            "implementation_brief": payload.get("implementation_brief") or {},
            "implementation_provider_scientific_authority": False,
            "provenance": provenance,
            "state": "owner_review",
            "owner_approval": None,
            "created_at": _now(),
            "automatic_deployment_authorized": False,
            "scientific_publication_authorized": False,
        }
        record["record_id"] = _versioned_id("spec", specification_id, version, record)
        record["checksum"] = _digest(record)
        return self._write(self._root(owner_id) / "specifications" / specification_id / f"v{version}.json", record)

    def get_specification(self, owner_id: str, specification_id: str, version: int | None = None) -> dict[str, Any]:
        directory = self._root(owner_id) / "specifications" / specification_id
        if version is None:
            paths = sorted(directory.glob("v*.json"), key=lambda p: int(p.stem[1:])) if directory.exists() else []
            if not paths:
                raise FileNotFoundError(specification_id)
            return self._read(paths[-1])
        return self._read(directory / f"v{version}.json")

    def approve_specification(self, owner_id: str, specification_id: str, version: int, *, actor: str, rationale: str) -> dict[str, Any]:
        path = self._root(owner_id) / "specifications" / specification_id / f"v{version}.json"
        record = self._read(path)
        if record["state"] not in {"owner_review", "approved_for_implementation"}:
            raise ValueError("HOMEPAGE_SPEC_NOT_APPROVABLE")
        if not _text(rationale):
            raise ValueError("HOMEPAGE_APPROVAL_RATIONALE_REQUIRED")
        if record["state"] == "approved_for_implementation":
            return record
        record["state"] = "approved_for_implementation"
        record["owner_approval"] = {"actor": actor, "rationale": rationale.strip(), "approved_at": _now(), "specification_checksum": record["checksum"]}
        return self._write(path, record)

    def receive_implementation(self, owner_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        implementation_id = _text(payload.get("implementation_id"))
        specification_id = _text(payload.get("specification_id"))
        specification_version = int(payload.get("specification_version", 0))
        deployed_revision = _text(payload.get("implementation_revision"))
        if not implementation_id or not specification_id or specification_version < 1 or not deployed_revision:
            raise ValueError("HOMEPAGE_IMPLEMENTATION_IDENTITY_REQUIRED")
        specification = self.get_specification(owner_id, specification_id, specification_version)
        if specification["state"] != "approved_for_implementation":
            raise ValueError("HOMEPAGE_SPEC_OWNER_APPROVAL_REQUIRED")
        manifest = payload.get("manifest")
        if not isinstance(manifest, dict):
            raise TypeError("HOMEPAGE_IMPLEMENTATION_MANIFEST_REQUIRED")
        screenshots_raw = list(payload.get("implementation_screenshots") or [])
        if not screenshots_raw:
            raise ValueError("HOMEPAGE_IMPLEMENTATION_SCREENSHOTS_REQUIRED")
        record = {
            "schema_version": SCHEMA_VERSION,
            "implementation_id": implementation_id,
            "specification_ref": {
                "specification_id": specification_id,
                "version": specification_version,
                "checksum": specification["checksum"],
            },
            "implementation_revision": deployed_revision,
            "manifest": manifest,
            "implementation_screenshots": [_screenshot(dict(item)) for item in screenshots_raw],
            "returned_artifact_metadata": list(payload.get("returned_artifact_metadata") or []),
            "implementation_provider": _text(payload.get("implementation_provider")) or None,
            "implementation_provider_scientific_authority": False,
            "received_at": _now(),
            "state": "implementation_received",
            "automatic_deployment_authorized": False,
            "scientific_publication_authorized": False,
        }
        record["checksum"] = _digest(record)
        return self._write(self._root(owner_id) / "implementations" / f"{implementation_id}.json", record)

    def get_implementation(self, owner_id: str, implementation_id: str) -> dict[str, Any]:
        return self._read(self._root(owner_id) / "implementations" / f"{implementation_id}.json")

    def validate(self, owner_id: str, implementation_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        implementation = self.get_implementation(owner_id, implementation_id)
        spec_ref = implementation["specification_ref"]
        specification = self.get_specification(owner_id, spec_ref["specification_id"], int(spec_ref["version"]))
        manifest = implementation["manifest"]
        sections = {_text(item) for item in manifest.get("sections", []) if _text(item)}
        routes = {_text(item) for item in manifest.get("routes", []) if _text(item)}
        components = {_text(item) for item in manifest.get("components", []) if _text(item)}
        missing_sections = sorted(set(specification["required_sections"]) - sections)
        missing_routes = sorted(set(specification["required_routes"]) - routes)
        missing_components = sorted(set(specification["required_components"]) - components)

        checks = payload.get("checks") or {}
        if not isinstance(checks, dict):
            raise TypeError("HOMEPAGE_VALIDATION_CHECKS_REQUIRED")
        required_checks = ("visual", "accessibility", "scientific", "taxonomy", "media", "evidence")
        normalized_checks: dict[str, dict[str, Any]] = {}
        for name in required_checks:
            item = checks.get(name)
            if not isinstance(item, dict):
                raise TypeError(f"HOMEPAGE_VALIDATION_CHECK_REQUIRED:{name}")
            passed = item.get("passed") is True
            evidence = list(item.get("evidence") or [])
            if passed and not evidence:
                raise ValueError(f"HOMEPAGE_VALIDATION_EVIDENCE_REQUIRED:{name}")
            normalized_checks[name] = {"passed": passed, "evidence": evidence, "findings": list(item.get("findings") or [])}

        taxon_results: list[dict[str, Any]] = []
        for taxon_id in sorted({_text(item) for item in manifest.get("taxon_references", []) if _text(item)}):
            try:
                dossier = self.dossiers.get(owner_id, taxon_id)
                taxon_results.append({"stable_taxon_id": taxon_id, "state": "resolved", "dossier_digest": dossier["dossier_digest"]})
            except FileNotFoundError:
                taxon_results.append({"stable_taxon_id": taxon_id, "state": "unresolved", "dossier_digest": None})
        unresolved_taxa = [item["stable_taxon_id"] for item in taxon_results if item["state"] != "resolved"]

        blockers: list[str] = []
        blockers.extend(f"missing_section:{item}" for item in missing_sections)
        blockers.extend(f"missing_route:{item}" for item in missing_routes)
        blockers.extend(f"missing_component:{item}" for item in missing_components)
        blockers.extend(f"unresolved_taxon:{item}" for item in unresolved_taxa)
        blockers.extend(f"failed_check:{name}" for name, item in normalized_checks.items() if not item["passed"])

        validation = {
            "schema_version": SCHEMA_VERSION,
            "implementation_id": implementation_id,
            "specification_ref": spec_ref,
            "specification_match": {
                "passed": not (missing_sections or missing_routes or missing_components),
                "missing_sections": missing_sections,
                "missing_routes": missing_routes,
                "missing_components": missing_components,
            },
            "checks": normalized_checks,
            "canonical_taxon_resolution": taxon_results,
            "blockers": blockers,
            "validated_at": _now(),
            "state": "validated" if not blockers else "validation_failed",
            "automatic_deployment_authorized": False,
            "scientific_publication_authorized": False,
        }
        validation["checksum"] = _digest(validation)
        self._write(self._root(owner_id) / "validations" / f"{implementation_id}.json", validation)
        implementation["state"] = validation["state"]
        self._write(self._root(owner_id) / "implementations" / f"{implementation_id}.json", implementation)
        return validation

    def readiness(self, owner_id: str, implementation_id: str) -> dict[str, Any]:
        implementation = self.get_implementation(owner_id, implementation_id)
        validation_path = self._root(owner_id) / "validations" / f"{implementation_id}.json"
        validation = self._read(validation_path) if validation_path.exists() else None
        blockers = list(validation.get("blockers") or []) if validation else ["validation_not_completed"]
        required_pass = bool(validation) and all(item.get("passed") is True for item in validation["checks"].values())
        spec_pass = bool(validation) and validation["specification_match"]["passed"] is True
        taxa_pass = bool(validation) and all(item["state"] == "resolved" for item in validation["canonical_taxon_resolution"])
        eligible = bool(validation and validation["state"] == "validated" and required_pass and spec_pass and taxa_pass and not blockers)
        state = "release_eligible" if eligible else (validation["state"] if validation else implementation["state"])
        if eligible and implementation["state"] != "release_eligible":
            implementation["state"] = "release_eligible"
            self._write(self._root(owner_id) / "implementations" / f"{implementation_id}.json", implementation)
        return {
            "schema_version": SCHEMA_VERSION,
            "implementation_id": implementation_id,
            "state": state,
            "release_eligible": eligible,
            "blockers": blockers,
            "visual_accessibility_scientific_evidence_gate_passed": required_pass,
            "specification_match_passed": spec_pass,
            "canonical_taxonomy_gate_passed": taxa_pass,
            "owner_activation_required": True,
            "automatic_deployment_authorized": False,
            "scientific_publication_authorized": False,
            "unreviewed_activation_authorized": False,
        }
