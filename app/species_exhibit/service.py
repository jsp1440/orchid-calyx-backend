from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row


CONTRACT = "calyx-species-exhibit-v1"


def _state(value: Any, *, limitation: str | None = None) -> dict[str, Any]:
    return {
        "state": "available" if value not in (None, [], {}) else "unavailable",
        "value": value,
        "limitation": limitation,
    }


def _graph_rows(cur, taxon_id: str) -> list[dict[str, Any]]:
    cur.execute("SELECT to_regclass('oc_graph.kg_nodes') IS NOT NULL, to_regclass('oc_graph.kg_edges') IS NOT NULL")
    present = cur.fetchone()
    if not present or not all(present.values()):
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


def build_species_exhibit(dsn: str, genus: str, limit: int = 9) -> dict[str, Any]:
    limit = max(1, min(limit, 24))
    accepted_genus = " ".join(genus.strip().split())
    with psycopg.connect(dsn, row_factory=dict_row, connect_timeout=8) as conn:
        with conn.cursor() as cur:
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
                (accepted_genus, limit),
            )
            taxa = [dict(row) for row in cur.fetchall()]
            items: list[dict[str, Any]] = []
            for taxon in taxa:
                cur.execute(
                    """
                    SELECT id, image_url, image_source, image_license,
                           image_rights_holder, observer_name, gbif_occurrence_key
                    FROM public.orchid_images
                    WHERE taxonomy_id = %s
                      AND image_url IS NOT NULL
                      AND COALESCE(is_duplicate, false) = false
                    ORDER BY id
                    LIMIT 3
                    """,
                    (taxon["id"],),
                )
                media = [dict(row) for row in cur.fetchall()]
                graph = _graph_rows(cur, str(taxon["id"]))
                evidence_states = {
                    "identity": _state({"taxon_id": str(taxon["id"]), "scientific_name": taxon["scientific_name"], "genus": taxon["genus"]}),
                    "media": _state(media, limitation=None if media else "No usable canonical media rows were found."),
                    "knowledge_graph": _state(graph, limitation=None if graph else "No persisted outgoing Knowledge Graph edges were found for this taxon."),
                    "morphology": _state(None, limitation="No canonical morphology adapter is connected to this packet yet."),
                    "occurrences": _state(None, limitation="No canonical occurrence adapter is connected to this packet yet."),
                    "pollinators": _state(None, limitation="No canonical pollinator adapter is connected to this packet yet."),
                    "mycorrhiza": _state(None, limitation="No canonical mycorrhizal adapter is connected to this packet yet."),
                    "literature": _state(None, limitation="No canonical literature adapter is connected to this packet yet."),
                    "conservation": _state(None, limitation="No canonical conservation adapter is connected to this packet yet."),
                }
                items.append({
                    "taxon_id": str(taxon["id"]),
                    "scientific_name": taxon["scientific_name"],
                    "genus": taxon["genus"],
                    "image_count": int(taxon["image_count"] or 0),
                    "media": media,
                    "graph_paths": graph,
                    "evidence_states": evidence_states,
                    "calyx_handoff": {
                        "contract": "calyx-species-narrative-input-v1",
                        "taxon_id": str(taxon["id"]),
                        "scientific_name": taxon["scientific_name"],
                        "evidence_states": evidence_states,
                        "instruction": "Generate only evidence-supported species-specific narrative; preserve unavailable and conflicting states.",
                    },
                })
    return {
        "contract": CONTRACT,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "requested_genus": genus,
        "accepted_genus": accepted_genus,
        "count": len(items),
        "items": items,
        "publication_authority": False,
        "graph_mutation": False,
    }
