"""Read-only comparison of external intelligence against Continuum knowledge stores.

This module may inspect canonical and candidate registries, but it never mutates
those stores.  A lack of a match is not treated as proof that a scientific claim
is novel: unmatched items remain REQUIRES_REVIEW until primary-source evidence
has been verified.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

import psycopg
from psycopg.rows import dict_row

from .repository import database_url


@dataclass(frozen=True)
class KnowledgeDeltaAssessment:
    item_id: int
    knowledge_delta: str
    candidate_delta: str | None
    confidence: float
    reason: str
    matches: tuple[dict[str, Any], ...]
    stores_checked: tuple[str, ...]
    verification_required: bool = True
    canonical_graph_mutated: bool = False
    external_contacted: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "knowledge_delta": self.knowledge_delta,
            "candidate_delta": self.candidate_delta,
            "confidence": self.confidence,
            "reason": self.reason,
            "matches": list(self.matches),
            "stores_checked": list(self.stores_checked),
            "verification_required": self.verification_required,
            "canonical_graph_mutated": False,
            "external_contacted": False,
        }


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).lower()


def _table_exists(cur: psycopg.Cursor, schema: str, table: str) -> bool:
    cur.execute("SELECT to_regclass(%s) IS NOT NULL AS present", (f"{schema}.{table}",))
    row = cur.fetchone()
    return bool(row and row["present"])


def _fetch_item(cur: psycopg.Cursor, item_id: int) -> dict[str, Any] | None:
    cur.execute(
        """
        SELECT id, domain, title, normalized_title, current_detail, source_urls, dois,
               canonical_destinations, verification_required, lifecycle, knowledge_delta
        FROM oc_intake.intelligence_items
        WHERE id=%s
        """,
        (item_id,),
    )
    return cur.fetchone()


def _source_registry_matches(cur: psycopg.Cursor, item: dict[str, Any]) -> list[dict[str, Any]]:
    if not _table_exists(cur, "oc_sources", "sources"):
        return []
    title = _normalize(str(item["title"]))
    tokens = [token for token in re.findall(r"[a-z0-9@.+-]+", title) if len(token) >= 4]
    if not tokens:
        return []
    cur.execute(
        """
        SELECT source_id::text AS source_id, source_name, source_type, status, configuration
        FROM oc_sources.sources
        WHERE status IN ('ACTIVE','PAUSED')
        ORDER BY source_name
        """
    )
    matches = []
    for row in cur.fetchall():
        normalized_name = _normalize(str(row["source_name"]))
        if normalized_name in title or title in normalized_name or sum(token in normalized_name for token in tokens) >= 2:
            matches.append({
                "store": "source_registry",
                "kind": "source",
                "id": row["source_id"],
                "label": row["source_name"],
                "source_type": row["source_type"],
                "status": row["status"],
            })
    return matches[:10]


def _doi_matches(cur: psycopg.Cursor, item: dict[str, Any]) -> list[dict[str, Any]]:
    dois = [str(value).strip().lower() for value in (item.get("dois") or []) if str(value).strip()]
    if not dois:
        return []
    matches: list[dict[str, Any]] = []

    if _table_exists(cur, "oc_intake", "sources"):
        for doi in dois:
            cur.execute(
                """
                SELECT id, title, source_type, source_url, status
                FROM oc_intake.sources
                WHERE lower(COALESCE(source_url,'')) LIKE %s
                   OR lower(COALESCE(raw_content,'')) LIKE %s
                ORDER BY imported_at DESC
                LIMIT 10
                """,
                (f"%{doi}%", f"%{doi}%"),
            )
            for row in cur.fetchall():
                matches.append({
                    "store": "intake_sources",
                    "kind": "document_or_source",
                    "id": row["id"],
                    "label": row["title"],
                    "source_type": row["source_type"],
                    "status": row["status"],
                    "matched_doi": doi,
                })
    return matches[:20]


def _ontology_matches(cur: psycopg.Cursor, item: dict[str, Any]) -> list[dict[str, Any]]:
    if not _table_exists(cur, "oc_ontology", "ontology_terms"):
        return []
    title = _normalize(str(item["title"]))
    detail = _normalize(str(item.get("current_detail") or ""))
    combined = f" {title} {detail} "
    cur.execute(
        """
        SELECT t.id, t.preferred_label, t.normalized_label, t.term_type,
               r.namespace, r.name AS registry_name, r.version
        FROM oc_ontology.ontology_terms t
        JOIN oc_ontology.ontology_registries r ON r.id=t.registry_id
        WHERE t.status IN ('ACTIVE','DRAFT')
          AND length(t.normalized_label) >= 4
        ORDER BY length(t.normalized_label) DESC
        LIMIT 5000
        """
    )
    matches = []
    for row in cur.fetchall():
        label = _normalize(str(row["normalized_label"]))
        if f" {label} " in combined:
            matches.append({
                "store": "ontology",
                "kind": "term",
                "id": row["id"],
                "label": row["preferred_label"],
                "term_type": row["term_type"],
                "namespace": row["namespace"],
                "registry": row["registry_name"],
                "version": row["version"],
            })
            if len(matches) >= 25:
                break
    return matches


def _candidate_delta(item: dict[str, Any]) -> str:
    domain = str(item["domain"])
    text = _normalize(f"{item['title']} {item.get('current_detail') or ''}")
    destinations = {str(value) for value in (item.get("canonical_destinations") or [])}

    if domain == "technology" or "source_registry" in destinations:
        if any(marker in text for marker in ("api", "dataset", "platform", "earth engine", "open source", "open-source")):
            return "NEW_SOURCE"
        return "CAPABILITY_GAP"
    if domain == "research":
        if any(marker in text for marker in ("pollinator", "pollination", "mycorrhiz", "fungal", "interaction", "relationship")):
            return "NEW_RELATIONSHIP"
        return "NEW_EVIDENCE"
    if domain == "taxonomy":
        return "NEW_EVIDENCE"
    if domain == "partnerships":
        return "NEW_ENTITY"
    if domain == "conservation":
        return "NEW_EVIDENCE"
    if domain == "funding":
        return "NEW_ENTITY"
    return "REQUIRES_REVIEW"


def assess_item(item_id: int) -> KnowledgeDeltaAssessment:
    """Compare one intelligence item against available read-only Continuum stores."""
    with psycopg.connect(database_url(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            item = _fetch_item(cur, item_id)
            if not item:
                raise KeyError("INTELLIGENCE_ITEM_NOT_FOUND")

            stores_checked = ["intelligence_ledger"]
            doi_matches = _doi_matches(cur, item)
            if _table_exists(cur, "oc_intake", "sources"):
                stores_checked.append("intake_sources")

            source_matches = _source_registry_matches(cur, item)
            if _table_exists(cur, "oc_sources", "sources"):
                stores_checked.append("source_registry")

            ontology_matches = _ontology_matches(cur, item)
            if _table_exists(cur, "oc_ontology", "ontology_terms"):
                stores_checked.append("ontology")

            matches = doi_matches + source_matches + ontology_matches
            strong_matches = doi_matches + source_matches

            if strong_matches:
                return KnowledgeDeltaAssessment(
                    item_id=item_id,
                    knowledge_delta="ALREADY_KNOWN",
                    candidate_delta=None,
                    confidence=0.95 if doi_matches else 0.85,
                    reason=(
                        "The Continuum already contains a strong identifier/source-registry match. "
                        "The external briefing may still add newer evidence, so primary-source verification remains required."
                    ),
                    matches=tuple(matches),
                    stores_checked=tuple(dict.fromkeys(stores_checked)),
                )

            candidate = _candidate_delta(item)
            return KnowledgeDeltaAssessment(
                item_id=item_id,
                knowledge_delta="REQUIRES_REVIEW",
                candidate_delta=candidate,
                confidence=0.55 if ontology_matches else 0.4,
                reason=(
                    "No strong DOI or registered-source match was found in the checked Continuum stores. "
                    f"This is a candidate {candidate}, not a confirmed novelty claim; verify the primary source before promotion."
                ),
                matches=tuple(matches),
                stores_checked=tuple(dict.fromkeys(stores_checked)),
            )
