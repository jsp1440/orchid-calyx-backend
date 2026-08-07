from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row


CONTRACT = "calyx-species-exhibit-v1"
EVIDENCE_DOMAINS = (
    "identity",
    "media",
    "knowledge_graph",
    "morphology",
    "occurrences",
    "pollinators",
    "mycorrhiza",
    "literature",
    "conservation",
)


def _state(value: Any, *, limitation: str | None = None) -> dict[str, Any]:
    return {
        "state": "available" if value not in (None, [], {}) else "unavailable",
        "value": value,
        "limitation": limitation,
    }


def _split_scientific_name(value: str) -> tuple[str, str | None]:
    """Separate the normalized binomial from any retained authorship text."""
    normalized = " ".join((value or "").strip().split())
    if not normalized:
        return "", None
    parts = normalized.split(" ")
    if len(parts) < 2:
        return normalized, None
    display_name = " ".join(parts[:2])
    authorship = " ".join(parts[2:]).strip() or None
    return display_name, authorship


def _normalized_name(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def _representative_media(
    media: list[dict[str, Any]], used_urls: set[str]
) -> dict[str, Any] | None:
    """Choose the first deterministic media row not already used by another card."""
    for row in media:
        url = str(row.get("image_url") or "").strip()
        if not url or url in used_urls:
            continue
        used_urls.add(url)
        return {
            "id": row.get("id"),
            "url": url,
            "source": row.get("image_source"),
            "license": row.get("image_license"),
            "rights_holder": row.get("image_rights_holder"),
            "observer_name": row.get("observer_name"),
            "gbif_occurrence_key": row.get("gbif_occurrence_key"),
            "identification_state": "source_record_not_independently_verified",
        }
    return None


def _graph_fact(
    display_name: str, graph: list[dict[str, Any]]
) -> tuple[str | None, str | None, dict[str, Any] | None]:
    """Render only an already persisted graph relation; never invent a species claim."""
    for row in graph:
        label = str(row.get("display_label") or "").strip()
        edge_type = str(row.get("edge_type") or "").strip()
        if not label or not edge_type:
            continue
        edge_phrase = edge_type.replace("_", " ").strip()
        distinguishing_fact = f"{display_name} — {edge_phrase}: {label}"
        caption = f"{display_name}: {edge_phrase} — {label}."
        provenance = {
            "source_table": row.get("source_table"),
            "source_pk": row.get("source_pk"),
            "evidence_class": row.get("evidence_class"),
            "confidence_score": row.get("confidence_score"),
            "confidence_label": row.get("confidence_label"),
        }
        return caption, distinguishing_fact, provenance
    return None, None, None


def _confidence(graph: list[dict[str, Any]]) -> dict[str, Any]:
    scored: list[tuple[float, dict[str, Any]]] = []
    for row in graph:
        value = row.get("confidence_score")
        if value is None or isinstance(value, bool):
            continue
        try:
            score = float(value)
        except (TypeError, ValueError, OverflowError):
            continue
        scored.append((score, row))
    if not scored:
        return {
            "state": "unavailable",
            "score": None,
            "label": None,
            "basis": "No persisted graph confidence score is available.",
        }
    score, row = max(scored, key=lambda item: item[0])
    return {
        "state": "available",
        "score": score,
        "label": row.get("confidence_label"),
        "basis": "Maximum explicit confidence score among returned persisted graph edges.",
    }


def _contradictions(graph: list[dict[str, Any]]) -> list[dict[str, Any]]:
    contradiction_classes = {"conflict", "contradiction", "contradictory"}
    return [
        {
            "edge_type": row.get("edge_type"),
            "display_label": row.get("display_label"),
            "source_table": row.get("source_table"),
            "source_pk": row.get("source_pk"),
        }
        for row in graph
        if str(row.get("evidence_class") or "").strip().lower() in contradiction_classes
    ]


def _provenance_anchors(
    taxon_id: str,
    representative_media: dict[str, Any] | None,
    graph: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    anchors: list[dict[str, Any]] = [
        {"kind": "taxonomy", "source": "public.orchid_taxonomy", "record_id": taxon_id}
    ]
    if representative_media is not None:
        anchors.append(
            {
                "kind": "media",
                "source": representative_media.get("source") or "public.orchid_images",
                "record_id": representative_media.get("id"),
                "license": representative_media.get("license"),
            }
        )
    seen_graph: set[tuple[str, str]] = set()
    for row in graph:
        source_table = str(row.get("source_table") or "").strip()
        source_pk = str(row.get("source_pk") or "").strip()
        if not source_table and not source_pk:
            continue
        key = (source_table, source_pk)
        if key in seen_graph:
            continue
        seen_graph.add(key)
        anchors.append(
            {
                "kind": "knowledge_graph",
                "source": source_table or None,
                "record_id": source_pk or None,
            }
        )
    return anchors


def _evidence_receipt(
    taxon_id: str,
    representative_media: dict[str, Any] | None,
    graph: list[dict[str, Any]],
) -> dict[str, Any]:
    payload = {
        "taxon_id": taxon_id,
        "representative_media_url": (
            representative_media.get("url") if representative_media is not None else None
        ),
        "graph_sources": [
            {
                "source_table": row.get("source_table"),
                "source_pk": row.get("source_pk"),
                "edge_type": row.get("edge_type"),
            }
            for row in graph
        ],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return {
        "algorithm": "sha256",
        "digest": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "contents_included": False,
    }


def _graph_rows(cur, taxon_id: str) -> list[dict[str, Any]]:
    cur.execute(
        "SELECT to_regclass('oc_graph.kg_nodes') IS NOT NULL AS nodes_present, "
        "to_regclass('oc_graph.kg_edges') IS NOT NULL AS edges_present"
    )
    present = cur.fetchone()
    if not present or not present["nodes_present"] or not present["edges_present"]:
        return []
    cur.execute(
        """
        SELECT e.edge_type, n2.node_type, n2.canonical_key, n2.display_label,
               e.evidence_class, e.confidence_score, e.confidence_label,
               e.source_table, e.source_pk
        FROM oc_graph.kg_nodes n1
        JOIN oc_graph.kg_edges e ON e.from_node_id = n1.kg_node_id
        JOIN oc_graph.kg_nodes n2 ON n2.kg_node_id = e.to_node_id
        WHERE n1.canonical_key = %s
        ORDER BY e.kg_edge_id
        LIMIT 100
        """,
        (f"taxon:{taxon_id}",),
    )
    return [dict(row) for row in cur.fetchall()]


def _build_card(
    taxon: dict[str, Any],
    media: list[dict[str, Any]],
    graph: list[dict[str, Any]],
    used_media_urls: set[str],
) -> dict[str, Any]:
    taxon_id = str(taxon["id"])
    full_scientific_name = str(taxon["scientific_name"])
    display_name, authorship = _split_scientific_name(full_scientific_name)
    representative_media = _representative_media(media, used_media_urls)
    caption, distinguishing_fact, fact_provenance = _graph_fact(display_name, graph)

    evidence_states = {
        "identity": _state(
            {
                "taxon_id": taxon_id,
                "display_name": display_name,
                "full_scientific_name": full_scientific_name,
                "authorship": authorship,
                "genus": taxon["genus"],
            }
        ),
        "media": _state(
            representative_media,
            limitation=(
                None
                if representative_media is not None
                else "No unique usable canonical media row was found for this taxon."
            ),
        ),
        "knowledge_graph": _state(
            graph,
            limitation=(
                None
                if graph
                else "No persisted outgoing Knowledge Graph edges were found for this taxon."
            ),
        ),
        "morphology": _state(
            None, limitation="No canonical morphology adapter is connected to this packet yet."
        ),
        "occurrences": _state(
            None, limitation="No canonical occurrence adapter is connected to this packet yet."
        ),
        "pollinators": _state(
            None, limitation="No canonical pollinator adapter is connected to this packet yet."
        ),
        "mycorrhiza": _state(
            None,
            limitation="No canonical mycorrhizal adapter is connected to this packet yet.",
        ),
        "literature": _state(
            None, limitation="No canonical literature adapter is connected to this packet yet."
        ),
        "conservation": _state(
            None,
            limitation="No canonical conservation adapter is connected to this packet yet.",
        ),
    }
    unavailable_domains = [
        domain for domain in EVIDENCE_DOMAINS if evidence_states[domain]["state"] == "unavailable"
    ]
    contradictions = _contradictions(graph)
    caveats: list[str] = []
    if caption is None:
        caveats.append(
            "No species-specific caption is currently supported by connected graph evidence."
        )
    if representative_media is None:
        caveats.append("No unique representative image is currently available for this card.")
    if contradictions:
        caveats.append("Persisted Knowledge Graph evidence contains contradiction markers.")

    evidence_state = "available" if caption and representative_media else "provisional"
    provenance = _provenance_anchors(taxon_id, representative_media, graph)
    receipt = _evidence_receipt(taxon_id, representative_media, graph)
    return {
        "taxon_id": taxon_id,
        "display_name": display_name,
        "full_scientific_name": full_scientific_name,
        "authorship": authorship,
        "accepted_name_status": "canonical_table_record",
        "genus": taxon["genus"],
        "image_count": int(taxon["image_count"] or 0),
        "representative_media": representative_media,
        "media": media,
        "caption": caption,
        "distinguishing_fact": distinguishing_fact,
        "distinguishing_fact_provenance": fact_provenance,
        "evidence_state": evidence_state,
        "confidence": _confidence(graph),
        "provenance": provenance,
        "unavailable_domains": unavailable_domains,
        "contradictions": contradictions,
        "caveats": caveats,
        "links": {
            "species": f"/species/{taxon_id}",
            "graph": f"/intelligence-graph?taxon_id={taxon_id}",
            "evidence": f"/api/platform/homepage/species/{taxon_id}/evidence",
        },
        "graph_paths": graph,
        "evidence_states": evidence_states,
        "evidence_receipt": receipt,
        "calyx_handoff": {
            "contract": "calyx-species-narrative-input-v1",
            "taxon_id": taxon_id,
            "display_name": display_name,
            "full_scientific_name": full_scientific_name,
            "evidence_states": evidence_states,
            "instruction": (
                "Generate only evidence-supported species-specific narrative; preserve unavailable "
                "and conflicting states."
            ),
        },
    }


def build_species_exhibit(dsn: str, genus: str, limit: int = 9) -> dict[str, Any]:
    limit = max(1, min(limit, 24))
    accepted_genus = " ".join(genus.strip().split())
    candidate_limit = min(limit * 4, 96)
    with (
        psycopg.connect(dsn, row_factory=dict_row, connect_timeout=8) as conn,
        conn.cursor() as cur,
    ):
        cur.execute(
            """
            SELECT t.id, t.scientific_name, t.genus,
                   COUNT(i.id) AS image_count
            FROM public.orchid_taxonomy t
            LEFT JOIN public.orchid_images i
              ON i.taxonomy_id = t.id
             AND i.image_url IS NOT NULL
             AND COALESCE(i.is_duplicate, false) = false
            WHERE lower(t.genus) = lower(%s)
            GROUP BY t.id, t.scientific_name, t.genus
            ORDER BY COUNT(i.id) DESC, t.scientific_name
            LIMIT %s
            """,
            (accepted_genus, candidate_limit),
        )
        taxa = [dict(row) for row in cur.fetchall()]
        items: list[dict[str, Any]] = []
        seen_taxa: set[str] = set()
        seen_names: set[str] = set()
        used_media_urls: set[str] = set()
        for taxon in taxa:
            taxon_id = str(taxon["id"])
            display_name, _ = _split_scientific_name(str(taxon["scientific_name"]))
            normalized_name = _normalized_name(display_name)
            if taxon_id in seen_taxa or not normalized_name or normalized_name in seen_names:
                continue
            cur.execute(
                """
                SELECT id, image_url, image_source, image_license,
                       image_rights_holder, observer_name, gbif_occurrence_key
                FROM public.orchid_images
                WHERE taxonomy_id = %s
                  AND image_url IS NOT NULL
                  AND COALESCE(is_duplicate, false) = false
                ORDER BY id
                LIMIT 5
                """,
                (taxon["id"],),
            )
            media = [dict(row) for row in cur.fetchall()]
            graph = _graph_rows(cur, taxon_id)
            item = _build_card(taxon, media, graph, used_media_urls)
            items.append(item)
            seen_taxa.add(taxon_id)
            seen_names.add(normalized_name)
            if len(items) >= limit:
                break
    return {
        "contract": CONTRACT,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "requested_genus": genus,
        "accepted_genus": accepted_genus,
        "count": len(items),
        "requested_limit": limit,
        "distinct_taxa": len({item["taxon_id"] for item in items}),
        "items": items,
        "publication_authority": False,
        "graph_mutation": False,
    }
