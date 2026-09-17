"""Postgres-backed species repository for the dossier contract (``oc-species-dossier-v1``).

Reads only what Calyx already holds and says so section by section:

* identity from ``public.orchid_taxonomy`` (the same table the homepage
  species exhibit reads);
* living media from ``public.orchid_images`` with licence and attribution
  receipts, marked provisional because a source record's identification is
  not independently verified here;
* knowledge-graph relations from ``oc_graph.kg_nodes`` / ``kg_edges`` when
  those tables exist, with their persisted source table and confidence;
* every other section ``unavailable`` with an explicit reason. Absence here
  is not evidence of absence in the literature.

No coordinates are read or emitted: the atlas envelope reports every layer
unavailable, so a species page can never leak locality through this path.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from typing import Any

from app.species_exhibit.service import (
    _split_scientific_name as split_display_name_and_authorship,
)

from .models import (
    DossierEvidenceState,
    DossierSection,
    EvidenceReceipt,
    SpeciesAtlasEnvelope,
    SpeciesDossierEnvelope,
    SpeciesIdentity,
)

TAXONOMY_TABLE = "public.orchid_taxonomy"
IMAGES_TABLE = "public.orchid_images"
NOT_ASSEMBLED = (
    "Not yet assembled from verified sources for this taxon. "
    "Absence here is not evidence of absence in the scientific literature."
)
ATLAS_UNAVAILABLE_LAYERS = [
    "occurrences",
    "range",
    "protected_areas",
    "elevation",
    "climate",
]
MAX_MEDIA = 12
MAX_GRAPH_EDGES = 100
MAX_RELATED = 8

DbExecute = Callable[[Callable[[Any], Any]], Any]


def split_scientific_name(value: str) -> tuple[str, str | None]:
    parts = " ".join(str(value or "").split()).split(" ")
    genus = parts[0] if parts and parts[0] else ""
    epithet = parts[1] if len(parts) > 1 and parts[1][:1].islower() else None
    return genus, epithet


def _unavailable(reason: str = NOT_ASSEMBLED) -> DossierSection:
    return DossierSection(state=DossierEvidenceState.UNAVAILABLE, unavailable_reason=reason)


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


class PostgresSpeciesRepository:
    """Implements :class:`app.species_dossier.service.SpeciesRepository` over Calyx's tables."""

    def __init__(self, db_execute: DbExecute, *, matrix_path: str = "/orchid-identification") -> None:
        self._db_execute = db_execute
        self._matrix_path = matrix_path

    # -- SpeciesRepository -----------------------------------------------------------------

    def get_dossier(self, taxon_id: str) -> SpeciesDossierEnvelope | None:
        def _work(cur: Any) -> SpeciesDossierEnvelope | None:
            if cur is None:
                return None
            taxon = self._taxon(cur, taxon_id)
            if taxon is None:
                return None
            identity = self._identity(taxon)
            media = self._media(cur, taxon["id"])
            graph = self._graph(cur, taxon["id"])
            related = self._related(cur, taxon["id"], identity.genus)
            generated_at = _now()
            return SpeciesDossierEnvelope(
                generated_at=generated_at,
                identity=identity,
                nomenclature=_unavailable(),
                protologue=_unavailable(),
                type_material=_unavailable(),
                historical_media=_unavailable(),
                living_media=media,
                morphology=_unavailable(),
                distribution=_unavailable(
                    "Distribution is not served through the dossier: occurrence and locality "
                    "records are protected and are never emitted by this path."
                ),
                ecology=_unavailable(),
                phenology=_unavailable(),
                pollinators=_unavailable(),
                mycorrhizae=_unavailable(),
                conservation=_unavailable(),
                literature=_unavailable(),
                cultivation=_unavailable(),
                knowledge_graph=graph,
                calyx_narrative=_unavailable(
                    "No Calyx narrative is published for this taxon; narratives require human scientific review."
                ),
                research_gaps=_unavailable(),
                atlas=self._atlas_envelope(str(taxon["id"]), generated_at),
                related_species=related,
                matrix_url=f"{self._matrix_path}?taxon_id={taxon['id']}",
                partner_references=[],
                provenance=[
                    EvidenceReceipt(
                        source_id=TAXONOMY_TABLE,
                        source_name="Orchid Continuum taxonomy table",
                        record_id=str(taxon["id"]),
                        retrieved_at=generated_at,
                        evidence_state=DossierEvidenceState.AVAILABLE,
                        notes="Identity record as stored; authorship and synonymy are not yet carried by this table.",
                    )
                ],
            )

        return self._db_execute(_work)

    def get_atlas(self, taxon_id: str) -> SpeciesAtlasEnvelope | None:
        def _work(cur: Any) -> SpeciesAtlasEnvelope | None:
            if cur is None:
                return None
            taxon = self._taxon(cur, taxon_id)
            if taxon is None:
                return None
            return self._atlas_envelope(str(taxon["id"]), _now())

        return self._db_execute(_work)

    def resolve_taxon_id(self, taxon_id: str) -> tuple[str, str] | None:
        def _work(cur: Any) -> tuple[str, str] | None:
            if cur is None:
                return None
            taxon = self._taxon(cur, taxon_id)
            return (str(taxon["id"]), str(taxon["scientific_name"])) if taxon else None

        return self._db_execute(_work)

    def resolve_name(self, normalized_name: str) -> Sequence[tuple[str, str, str]]:
        def _work(cur: Any) -> list[tuple[str, str, str]]:
            if cur is None:
                return []
            cur.execute(
                f"""
                SELECT id, scientific_name
                FROM {TAXONOMY_TABLE}
                WHERE lower(scientific_name) = lower(%s)
                   OR lower(split_part(scientific_name, ' ', 1) || ' ' || split_part(scientific_name, ' ', 2)) = lower(%s)
                ORDER BY scientific_name
                LIMIT 5
                """,
                (normalized_name, normalized_name),
            )
            # Only accepted names are stored in this table; synonym resolution
            # needs a synonymy source that is not yet available here.
            return [
                (
                    str(row["id"]),
                    split_display_name_and_authorship(str(row["scientific_name"]))[0] or str(row["scientific_name"]),
                    "accepted_name",
                )
                for row in cur.fetchall()
            ]

        return self._db_execute(_work) or []

    def resolve_partner_slug(self, partner_slug: str, species_slug: str) -> Sequence[tuple[str, str, str]]:
        # No partner slug mapping is stored yet; the service reports "unresolved".
        return []

    # -- internals --------------------------------------------------------------------------

    @staticmethod
    def _taxon(cur: Any, taxon_id: str) -> dict[str, Any] | None:
        cur.execute(
            f"SELECT id, scientific_name, genus FROM {TAXONOMY_TABLE} WHERE id::text = %s LIMIT 1",
            (str(taxon_id).strip(),),
        )
        row = cur.fetchone()
        return dict(row) if row else None

    @staticmethod
    def _identity(taxon: dict[str, Any]) -> SpeciesIdentity:
        scientific_name = str(taxon.get("scientific_name") or "").strip()
        genus_from_name, epithet = split_scientific_name(scientific_name)
        genus = str(taxon.get("genus") or genus_from_name or "").strip()
        # The same split the homepage species exhibit applies to the same row, so the
        # binomial a reader sees on the exhibit, the dossier and every continuation link
        # is one string, and authorship is stated separately rather than folded into it.
        display_name, authorship = split_display_name_and_authorship(scientific_name)
        return SpeciesIdentity(
            taxon_id=str(taxon["id"]),
            display_name=display_name or scientific_name,
            full_scientific_name=scientific_name,
            accepted_name=display_name or scientific_name,
            authorship=authorship,
            rank="species" if epithet else "genus",
            genus=genus,
            specific_epithet=epithet,
            taxonomic_status="recorded_in_orchid_taxonomy_table",
            synonyms=[],
        )

    def _media(self, cur: Any, taxon_id: Any) -> DossierSection:
        cur.execute(
            f"""
            SELECT id, image_url, image_source, image_license, image_rights_holder,
                   observer_name, gbif_occurrence_key
            FROM {IMAGES_TABLE}
            WHERE taxonomy_id = %s
              AND image_url IS NOT NULL
              AND COALESCE(is_duplicate, false) = false
            ORDER BY id
            LIMIT %s
            """,
            (taxon_id, MAX_MEDIA),
        )
        rows = [dict(row) for row in cur.fetchall()]
        if not rows:
            return _unavailable("No licensed living media is stored for this taxon.")
        items = [
            {
                "id": row.get("id"),
                "url": row.get("image_url"),
                "source": row.get("image_source"),
                "license": row.get("image_license"),
                "rights_holder": row.get("image_rights_holder"),
                "observer_name": row.get("observer_name"),
                "gbif_occurrence_key": row.get("gbif_occurrence_key"),
                "identification_state": "source_record_not_independently_verified",
            }
            for row in rows
        ]
        receipts = [
            EvidenceReceipt(
                source_id=IMAGES_TABLE,
                source_name=str(row.get("image_source") or "stored image record"),
                record_id=str(row.get("id")),
                license=row.get("image_license"),
                attribution=row.get("image_rights_holder") or row.get("observer_name"),
                evidence_state=DossierEvidenceState.PROVISIONAL,
                notes="Source record identification is not independently verified by Orchid Continuum.",
            )
            for row in rows
        ]
        return DossierSection(
            state=DossierEvidenceState.PROVISIONAL,
            summary=f"{len(rows)} stored image record{'s' if len(rows) != 1 else ''} with licence and attribution.",
            items=items,
            receipts=receipts,
        )

    def _graph(self, cur: Any, taxon_id: Any) -> DossierSection:
        cur.execute(
            "SELECT to_regclass('oc_graph.kg_nodes') IS NOT NULL AS nodes_present, "
            "to_regclass('oc_graph.kg_edges') IS NOT NULL AS edges_present"
        )
        present = cur.fetchone()
        if not present or not present["nodes_present"] or not present["edges_present"]:
            return _unavailable("The persisted knowledge graph is not provisioned in this database.")
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
            LIMIT %s
            """,
            (f"taxon:{taxon_id}", MAX_GRAPH_EDGES),
        )
        rows = [dict(row) for row in cur.fetchall()]
        if not rows:
            return _unavailable("No persisted knowledge-graph relation names this taxon yet.")
        items = [
            {
                "edge_type": row.get("edge_type"),
                "node_type": row.get("node_type"),
                "canonical_key": row.get("canonical_key"),
                "display_label": row.get("display_label"),
                "evidence_class": row.get("evidence_class"),
                "confidence_score": row.get("confidence_score"),
                "confidence_label": row.get("confidence_label"),
            }
            for row in rows
        ]
        receipts = [
            EvidenceReceipt(
                source_id=str(row.get("source_table") or "oc_graph.kg_edges"),
                source_name="Persisted knowledge graph edge",
                record_id=str(row.get("source_pk")) if row.get("source_pk") is not None else None,
                evidence_state=DossierEvidenceState.AVAILABLE,
                notes="Relation as persisted; confidence is the graph's own score, not a verdict.",
            )
            for row in rows
        ]
        return DossierSection(
            state=DossierEvidenceState.AVAILABLE,
            summary=f"{len(rows)} persisted graph relation{'s' if len(rows) != 1 else ''} name this taxon.",
            items=items,
            receipts=receipts,
        )

    @staticmethod
    def _related(cur: Any, taxon_id: Any, genus: str) -> list[dict[str, Any]]:
        if not genus:
            return []
        cur.execute(
            f"""
            SELECT id, scientific_name FROM {TAXONOMY_TABLE}
            WHERE lower(genus) = lower(%s) AND id::text <> %s
            ORDER BY scientific_name
            LIMIT %s
            """,
            (genus, str(taxon_id), MAX_RELATED),
        )
        return [
            {"taxon_id": str(row["id"]), "display_name": str(row["scientific_name"]), "relation": "same_genus"}
            for row in cur.fetchall()
        ]

    @staticmethod
    def _atlas_envelope(taxon_id: str, generated_at: datetime) -> SpeciesAtlasEnvelope:
        return SpeciesAtlasEnvelope(
            taxon_id=taxon_id,
            generated_at=generated_at,
            layers=[],
            unavailable_layers=list(ATLAS_UNAVAILABLE_LAYERS),
            provenance=[],
        )
