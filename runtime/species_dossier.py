"""Canonical, review-only species dossier and federation gateway for CALYX issue #467.

This module assembles governed upstream packets into one stable-taxon envelope. It does
not ingest from providers, mutate the Knowledge Graph, publish scientific conclusions,
or infer partner permissions. Missing domains remain explicitly unavailable.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "calyx-species-dossier/v1"
DOMAIN_NAMES = (
    "nomenclature",
    "media",
    "distribution",
    "atlas",
    "ecology",
    "pollination",
    "mycorrhiza",
    "conservation",
    "literature",
    "cultivation",
    "graph_paths",
)
PERMISSION_DIMENSIONS = ("link_out", "ingest", "redistribute", "derivative_use")
PERMISSION_STATES = {"allowed", "denied", "unknown", "not_applicable"}


def dossier_root() -> Path:
    return Path(os.environ.get("CALYX_SPECIES_DOSSIER_WORKSPACE", "/tmp/calyx/species-dossiers"))


def _text(value: object) -> str:
    return str(value or "").strip()


def _stable(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(payload: Any) -> str:
    return hashlib.sha256(_stable(payload).encode("utf-8")).hexdigest()


def _owner_key(owner_id: str) -> str:
    owner = _text(owner_id)
    if not owner:
        raise ValueError("DOSSIER_OWNER_REQUIRED")
    return hashlib.sha256(owner.casefold().encode()).hexdigest()[:20]


def _normalize_name(value: str) -> str:
    return " ".join(value.casefold().split())


def _normalize_domain(name: str, payload: Any) -> dict[str, Any]:
    if name not in DOMAIN_NAMES:
        raise ValueError(f"DOSSIER_DOMAIN_UNKNOWN:{name}")
    if payload is None:
        return {
            "domain": name,
            "state": "unavailable",
            "items": [],
            "provenance": [],
            "contradictions": [],
            "reason": "not_supplied",
        }
    if not isinstance(payload, dict):
        raise TypeError(f"DOSSIER_DOMAIN_INVALID:{name}")
    state = _text(payload.get("state")) or "available"
    if state not in {"available", "partial", "unavailable", "review_required"}:
        raise ValueError(f"DOSSIER_DOMAIN_STATE_INVALID:{name}")
    items = list(payload.get("items") or [])
    provenance = list(payload.get("provenance") or [])
    contradictions = list(payload.get("contradictions") or [])
    reason = _text(payload.get("reason")) or None
    if state in {"available", "partial", "review_required"} and not provenance:
        raise ValueError(f"DOSSIER_DOMAIN_PROVENANCE_REQUIRED:{name}")
    if state == "unavailable" and items:
        raise ValueError(f"DOSSIER_UNAVAILABLE_DOMAIN_HAS_ITEMS:{name}")
    return {
        "domain": name,
        "state": state,
        "items": items,
        "provenance": provenance,
        "contradictions": contradictions,
        "reason": reason,
    }


def _partner_link(payload: dict[str, Any]) -> dict[str, Any]:
    partner_id = _text(payload.get("partner_id"))
    url = _text(payload.get("url"))
    if not partner_id or not url:
        raise ValueError("DOSSIER_PARTNER_LINK_FIELDS_REQUIRED")
    permissions = payload.get("permissions") or {}
    if not isinstance(permissions, dict):
        raise TypeError("DOSSIER_PARTNER_PERMISSIONS_INVALID")
    normalized_permissions: dict[str, str] = {}
    for dimension in PERMISSION_DIMENSIONS:
        state = _text(permissions.get(dimension)) or "unknown"
        if state not in PERMISSION_STATES:
            raise ValueError(f"DOSSIER_PARTNER_PERMISSION_STATE_INVALID:{dimension}")
        normalized_permissions[dimension] = state
    evidence = list(payload.get("permission_evidence") or [])
    if any(state == "allowed" for state in normalized_permissions.values()) and not evidence:
        raise ValueError("DOSSIER_PARTNER_PERMISSION_EVIDENCE_REQUIRED")
    return {
        "partner_id": partner_id,
        "label": _text(payload.get("label")) or partner_id,
        "url": url,
        "permissions": normalized_permissions,
        "permission_evidence": evidence,
        "attribution": _text(payload.get("attribution")) or None,
        "permission_claims_inferred": False,
    }


class SpeciesDossierService:
    """Owner-scoped canonical dossier workspace with adaptive read-only resolution."""

    def __init__(self, workspace: Path | None = None) -> None:
        self.workspace = workspace or dossier_root()

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

    def assemble(self, owner_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        stable_taxon_id = _text(payload.get("stable_taxon_id"))
        identity = payload.get("identity")
        if not stable_taxon_id or not isinstance(identity, dict):
            raise ValueError("DOSSIER_CANONICAL_IDENTITY_REQUIRED")
        scientific_name = _text(identity.get("scientific_name"))
        if not scientific_name:
            raise ValueError("DOSSIER_SCIENTIFIC_NAME_REQUIRED")
        accepted_name_id = _text(identity.get("accepted_name_id")) or stable_taxon_id
        aliases = sorted({_text(item) for item in identity.get("aliases", []) if _text(item)})
        domains_input = payload.get("domains") or {}
        if not isinstance(domains_input, dict):
            raise TypeError("DOSSIER_DOMAINS_INVALID")
        unknown = sorted(set(domains_input) - set(DOMAIN_NAMES))
        if unknown:
            raise ValueError(f"DOSSIER_UNKNOWN_DOMAINS:{','.join(unknown)}")
        domains = {name: _normalize_domain(name, domains_input.get(name)) for name in DOMAIN_NAMES}
        unavailable = [name for name, item in domains.items() if item["state"] == "unavailable"]
        partial = [name for name, item in domains.items() if item["state"] in {"partial", "review_required"}]
        contradictions = [
            {"domain": name, "items": item["contradictions"]}
            for name, item in domains.items()
            if item["contradictions"]
        ]
        partner_links = [_partner_link(item) for item in list(payload.get("partner_links") or [])]
        partner_links.sort(key=lambda item: (item["partner_id"].casefold(), item["url"]))
        provenance = list(payload.get("provenance") or [])
        if not provenance:
            raise ValueError("DOSSIER_ENVELOPE_PROVENANCE_REQUIRED")

        envelope = {
            "schema_version": SCHEMA_VERSION,
            "stable_taxon_id": stable_taxon_id,
            "identity": {
                "stable_taxon_id": stable_taxon_id,
                "accepted_name_id": accepted_name_id,
                "scientific_name": scientific_name,
                "rank": _text(identity.get("rank")) or None,
                "authorship": _text(identity.get("authorship")) or None,
                "aliases": aliases,
            },
            "domains": domains,
            "unavailable_domains": unavailable,
            "partial_or_review_domains": partial,
            "contradiction_states": contradictions,
            "partner_links": partner_links,
            "provenance": provenance,
            "graceful_degradation": True,
            "partner_permission_claims_inferred": False,
            "production_ingestion_authorized": False,
            "production_graph_mutation_authorized": False,
            "scientific_publication_authorized": False,
            "production_deployment_authorized": False,
        }
        envelope["dossier_digest"] = _digest(envelope)
        path = self._root(owner_id) / "dossiers" / f"{stable_taxon_id}.json"
        if path.exists():
            existing = self._read(path)
            if existing.get("dossier_digest") == envelope["dossier_digest"]:
                return existing
        self._write(path, envelope)
        self._rebuild_index(owner_id)
        return envelope

    def _rebuild_index(self, owner_id: str) -> None:
        directory = self._root(owner_id) / "dossiers"
        records = [self._read(path) for path in sorted(directory.glob("*.json"))] if directory.exists() else []
        by_id: dict[str, str] = {}
        by_name: dict[str, list[str]] = {}
        for record in records:
            stable_id = record["stable_taxon_id"]
            by_id[stable_id] = stable_id
            names = [record["identity"]["scientific_name"], *record["identity"].get("aliases", [])]
            for name in names:
                by_name.setdefault(_normalize_name(name), []).append(stable_id)
        self._write(
            self._root(owner_id) / "index.json",
            {"schema_version": SCHEMA_VERSION, "by_id": by_id, "by_name": {k: sorted(set(v)) for k, v in by_name.items()}},
        )

    def get(self, owner_id: str, stable_taxon_id: str) -> dict[str, Any]:
        return self._read(self._root(owner_id) / "dossiers" / f"{stable_taxon_id}.json")

    def resolve(self, owner_id: str, query: str) -> dict[str, Any]:
        value = _text(query)
        if not value:
            raise ValueError("DOSSIER_RESOLVE_QUERY_REQUIRED")
        index_path = self._root(owner_id) / "index.json"
        if not index_path.exists():
            return {"state": "unmatched", "query": value, "candidate_ids": []}
        index = self._read(index_path)
        if value in index["by_id"]:
            return {"state": "matched", "method": "stable_taxon_id", "query": value, "stable_taxon_id": value, "dossier": self.get(owner_id, value)}
        candidates = index["by_name"].get(_normalize_name(value), [])
        if len(candidates) == 1:
            stable_id = candidates[0]
            return {"state": "matched", "method": "scientific_name_or_alias_exact", "query": value, "stable_taxon_id": stable_id, "dossier": self.get(owner_id, stable_id)}
        if len(candidates) > 1:
            return {"state": "ambiguous", "query": value, "candidate_ids": candidates}
        return {"state": "unmatched", "query": value, "candidate_ids": []}

    def readiness(self, owner_id: str, stable_taxon_id: str) -> dict[str, Any]:
        dossier = self.get(owner_id, stable_taxon_id)
        available = [name for name, item in dossier["domains"].items() if item["state"] == "available"]
        contradictions = dossier["contradiction_states"]
        return {
            "schema_version": SCHEMA_VERSION,
            "stable_taxon_id": stable_taxon_id,
            "decision": "DOSSIER_REVIEW_READY" if available else "IDENTITY_ONLY",
            "available_domains": available,
            "partial_or_review_domains": dossier["partial_or_review_domains"],
            "unavailable_domains": dossier["unavailable_domains"],
            "contradiction_domain_count": len(contradictions),
            "graceful_degradation": True,
            "partner_permission_claims_inferred": False,
            "production_ingestion_authorized": False,
            "production_graph_mutation_authorized": False,
            "scientific_publication_authorized": False,
            "production_deployment_authorized": False,
        }
