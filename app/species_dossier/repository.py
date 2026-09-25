"""Postgres-backed species repository for the dossier contract (``oc-species-dossier-v1``).

Reads only what Calyx already holds and says so section by section:

* identity from ``public.orchid_taxonomy`` (the same table the homepage
  species exhibit reads);
* living media from ``public.orchid_images`` with licence and attribution
  receipts, marked provisional because a source record's identification is
  not independently verified here;
* knowledge-graph relations from ``oc_graph.kg_nodes`` / ``kg_edges`` when
  those tables exist, with their persisted source table and confidence;
* federated compiled-specialist evidence (Gary Yong Gee, published by
  ``runtime/federated_sources/yong_gee.py`` as ``evidence`` nodes attached via
  ``supported_by_evidence`` edges) surfaced as ``provisional`` nomenclature,
  morphology, phenology and literature sections. Distribution and habitat
  prose is never read or emitted: it is withheld pending locality review;
* every other section ``unavailable`` with an explicit reason. Absence here
  is not evidence of absence in the literature.

No coordinates are read or emitted: the atlas envelope reports every layer
unavailable, so a species page can never leak locality through this path.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from typing import Any

from app.species_exhibit.service import (
    _split_scientific_name as split_display_name_and_authorship,
)
from app.species_exhibit.service import taxon_rank

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

# Federated compiled-specialist evidence (see runtime/federated_sources/yong_gee.py).
# Kept as literals so the request path does not import the ingestion module.
YONG_GEE_SOURCE_TABLE = "federated.gary_yong_gee_workbook"
YONG_GEE_SOURCE_NAME = "Gary Yong Gee Orchid Database"
YONG_GEE_ATTRIBUTION = "Gary Yong Gee (compiler)"
YONG_GEE_SUMMARY = (
    "Compiled by Gary Yong Gee; not independently verified by Orchid Continuum."
)
# Section -> evidence types, in display order.
FEDERATED_SECTION_TYPES: dict[str, tuple[str, ...]] = {
    "nomenclature": (
        "nomenclature",
        "nomenclatural_publication",
        "publication_year",
        "common_name",
        "taxonomy_section",
        "taxonomy_subsection",
        "etymology",
    ),
    "morphology": ("morphology", "fruit_capsule", "scent", "diagnostic_comparison"),
    "phenology": ("phenology",),
    "literature": ("bibliography",),
}
# Locality-sensitive: never selected, never emitted. Free-text notes are held
# back with them: prose can name a collecting site, and the coordinate screen
# only catches numeric coordinates, so they wait for locality-sensitivity review.
WITHHELD_EVIDENCE_TYPES = ("distribution", "habitat", "taxon_notes", "compiler_note")
# The evidence query spells out one placeholder per withheld type.
assert len(WITHHELD_EVIDENCE_TYPES) == 4
DISTRIBUTION_REASON = (
    "Distribution is not served through the dossier: occurrence and locality "
    "records are protected and are never emitted by this path. "
    "Distribution and habitat descriptions from federated sources are withheld "
    "pending locality-sensitivity review."
)
GRAPH_NOT_PROVISIONED = (
    "The persisted knowledge graph is not provisioned in this database."
)
MAX_FEDERATED_EVIDENCE = 200
MAX_SECTION_ITEMS = 12
MAX_EXCERPT_CHARS = 1200
TRUNCATION_MARKER = " [...]"
# Coordinate-looking text is withheld even from non-locality evidence types.
_COORDINATE_RE = re.compile(
    r"-?\b\d{1,3}\.\d{3,}\b|\d{1,3}\s*°\s*\d{0,2}\s*['′]?\s*\d{0,2}(?:\.\d+)?\s*[\"″]?\s*[NSEW]\b"
)
_WS_RE = re.compile(r"[ \t\f\v]+")

DbExecute = Callable[[Callable[[Any], Any]], Any]


def split_scientific_name(value: str) -> tuple[str, str | None]:
    parts = " ".join(str(value or "").split()).split(" ")
    genus = parts[0] if parts and parts[0] else ""
    epithet = parts[1] if len(parts) > 1 and parts[1][:1].islower() else None
    return genus, epithet


def _unavailable(reason: str = NOT_ASSEMBLED) -> DossierSection:
    return DossierSection(
        state=DossierEvidenceState.UNAVAILABLE, unavailable_reason=reason
    )


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


class PostgresSpeciesRepository:
    """Implements :class:`app.species_dossier.service.SpeciesRepository` over Calyx's tables."""

    def __init__(
        self, db_execute: DbExecute, *, matrix_path: str = "/orchid-identification"
    ) -> None:
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
            federated = self._federated_sections(cur, taxon["id"], graph)
            if "knowledge_graph" in federated:
                graph = federated.pop("knowledge_graph")
            related = self._related(cur, taxon["id"], identity.genus)
            generated_at = _now()
            candidate_unavailable = [
                "nomenclature",
                "protologue",
                "type_material",
                "historical_media",
                "morphology",
                "distribution",
                "ecology",
                "phenology",
                "pollinators",
                "mycorrhizae",
                "conservation",
                "literature",
                "cultivation",
                "calyx_narrative",
                "research_gaps",
                "atlas_summary",
                "identification_matrix",
            ]
            unavailable_sections = [
                name for name in candidate_unavailable if name not in federated
            ]
            return SpeciesDossierEnvelope(
                generated_at=generated_at,
                taxon_id=identity.taxon_id,
                display_name=identity.display_name,
                full_scientific_name=identity.full_scientific_name,
                accepted_name=identity.accepted_name,
                identity=identity,
                nomenclature=federated.get("nomenclature") or _unavailable(),
                protologue=_unavailable(),
                type_material=_unavailable(),
                historical_media=_unavailable(),
                living_media=media,
                morphology=federated.get("morphology") or _unavailable(),
                distribution=_unavailable(DISTRIBUTION_REASON),
                ecology=_unavailable(),
                phenology=federated.get("phenology") or _unavailable(),
                pollinators=_unavailable(),
                mycorrhizae=_unavailable(),
                conservation=_unavailable(),
                literature=federated.get("literature") or _unavailable(),
                cultivation=_unavailable(),
                knowledge_graph=graph,
                calyx_narrative=_unavailable(
                    "No Calyx narrative is published for this taxon; narratives require human scientific review."
                ),
                research_gaps=_unavailable(),
                atlas=self._atlas_envelope(str(taxon["id"]), generated_at),
                atlas_summary=_unavailable(
                    "Atlas layers are not assembled from a verified occurrence source in this path."
                ),
                identification_matrix=_unavailable(
                    "The identification matrix is not assembled from verified diagnostic evidence in this path."
                ),
                freshness={"state": "unknown", "as_of": None, "source": None},
                unavailable_sections=unavailable_sections,
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
            hits = [
                (
                    str(row["id"]),
                    split_display_name_and_authorship(str(row["scientific_name"]))[0]
                    or str(row["scientific_name"]),
                    "accepted_name",
                )
                for row in cur.fetchall()
            ]
            # The SQL also matches rows whose first two words equal the query, which
            # lets a species query reach its own infraspecific rows. When the query
            # names a row exactly, that row is the answer; otherwise every match is
            # returned and the service reports the ambiguity rather than guessing.
            wanted = " ".join(normalized_name.split()).lower()
            exact = [hit for hit in hits if hit[1].lower() == wanted]
            return exact or hits

        return self._db_execute(_work) or []

    def resolve_partner_slug(
        self, partner_slug: str, species_slug: str
    ) -> Sequence[tuple[str, str, str]]:
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
        # binomial a reader sees on the exhibit, the dossier and every continuation
        # link is one string, and authorship is stated separately rather than folded
        # into it.
        display_name, authorship = split_display_name_and_authorship(scientific_name)
        return SpeciesIdentity(
            taxon_id=str(taxon["id"]),
            display_name=display_name or scientific_name,
            full_scientific_name=scientific_name,
            accepted_name=display_name or scientific_name,
            authorship=authorship,
            rank=taxon_rank(display_name)
            if display_name
            else ("species" if epithet else "genus"),
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
              AND NULLIF(BTRIM(image_license), '') IS NOT NULL
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
            return _unavailable(GRAPH_NOT_PROVISIONED)
        cur.execute(
            """
            SELECT e.edge_type, n2.node_type, n2.canonical_key, n2.display_label,
                   e.evidence_class, e.confidence_score, e.confidence_label,
                   e.source_table, e.source_pk
            FROM oc_graph.kg_nodes n1
            JOIN oc_graph.kg_edges e ON e.from_node_id = n1.kg_node_id
            JOIN oc_graph.kg_nodes n2 ON n2.kg_node_id = e.to_node_id
            WHERE n1.canonical_key = %s
              AND e.edge_type <> 'supported_by_evidence'
              AND n1.is_active IS TRUE
              AND e.is_active IS TRUE
              AND n2.is_active IS TRUE
            ORDER BY e.kg_edge_id
            LIMIT %s
            """,
            (f"taxon:{taxon_id}", MAX_GRAPH_EDGES),
        )
        rows = [dict(row) for row in cur.fetchall()]
        if not rows:
            return _unavailable(
                "No persisted knowledge-graph relation names this taxon yet."
            )
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
                record_id=str(row.get("source_pk"))
                if row.get("source_pk") is not None
                else None,
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

    def _federated_sections(
        self, cur: Any, taxon_id: Any, graph: DossierSection
    ) -> dict[str, DossierSection]:
        """Provisional sections from compiled-specialist evidence nodes (read-only).

        Withheld types (distribution, habitat, free-text notes) are excluded in SQL
        and again here, and any excerpt with coordinate-looking text is withheld,
        so locality prose never leaves the database through this path.
        """
        if graph.unavailable_reason == GRAPH_NOT_PROVISIONED:
            return {}
        cur.execute(
            """
            SELECT ev.source_table, ev.source_pk, ev.payload_json, ev.updated_at
            FROM oc_graph.kg_nodes t
            JOIN oc_graph.kg_edges e ON e.from_node_id = t.kg_node_id
            JOIN oc_graph.kg_nodes ev ON ev.kg_node_id = e.to_node_id
            WHERE t.canonical_key = %s
              AND e.edge_type = 'supported_by_evidence'
              AND ev.node_type = 'evidence'
              AND ev.source_table = %s
              AND COALESCE(ev.payload_json->>'evidence_type', '') NOT IN (%s, %s, %s, %s)
              AND t.is_active IS TRUE
              AND e.is_active IS TRUE
              AND ev.is_active IS TRUE
            ORDER BY e.kg_edge_id
            LIMIT %s
            """,
            (
                f"taxon:{taxon_id}",
                YONG_GEE_SOURCE_TABLE,
                *WITHHELD_EVIDENCE_TYPES,
                MAX_FEDERATED_EVIDENCE,
            ),
        )
        by_type: dict[str, list[dict[str, Any]]] = {}
        for raw in cur.fetchall():
            row = dict(raw)
            payload = row.get("payload_json") or {}
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except ValueError:
                    continue
            if not isinstance(payload, dict):
                continue
            evidence_type = str(payload.get("evidence_type") or "")
            if not evidence_type or evidence_type in WITHHELD_EVIDENCE_TYPES:
                continue
            excerpt, truncated = _clean_excerpt(payload.get("excerpt"))
            if excerpt is None or _COORDINATE_RE.search(excerpt):
                continue
            by_type.setdefault(evidence_type, []).append(
                {
                    "row": row,
                    "payload": payload,
                    "excerpt": excerpt,
                    "truncated": truncated,
                }
            )

        sections: dict[str, DossierSection] = {}
        for section_name, types in FEDERATED_SECTION_TYPES.items():
            entries = [entry for t in types for entry in by_type.get(t, [])]
            if not entries:
                continue
            total = len(entries)
            entries = entries[:MAX_SECTION_ITEMS]
            items = [
                {
                    "evidence_type": entry["payload"].get("evidence_type"),
                    "excerpt": entry["excerpt"],
                    "excerpt_truncated": entry["truncated"],
                    "evidence_class": "compiled_specialist_source",
                    "evidence_state": DossierEvidenceState.PROVISIONAL.value,
                    "review_state": entry["payload"].get("review_state"),
                    "compiler": entry["payload"].get("compiler"),
                    "underlying_citation_status": entry["payload"].get(
                        "underlying_citation_status"
                    ),
                    "source_digest": entry["payload"].get("source_digest"),
                    "record_id": _str_or_none(entry["row"].get("source_pk")),
                }
                for entry in entries
            ]
            receipts = [_federated_receipt(entry) for entry in entries]
            if section_name == "knowledge_graph":
                noun = "note is" if len(items) == 1 else "notes are"
                sections[section_name] = DossierSection(
                    # The section now carries un-reviewed compiled-specialist text,
                    # so it is provisional as a whole, whatever the relations' state.
                    state=DossierEvidenceState.PROVISIONAL,
                    summary=(
                        f"{graph.summary or ''} {len(items)} compiled specialist "
                        f"{noun} provisional. {YONG_GEE_SUMMARY}"
                    ).strip(),
                    items=[*graph.items, *items],
                    receipts=[*graph.receipts, *receipts],
                )
                continue
            shown = (
                f"{len(items)} of {total}" if total > len(items) else f"{len(items)}"
            )
            sections[section_name] = DossierSection(
                state=DossierEvidenceState.PROVISIONAL,
                summary=(
                    f"{shown} compiled specialist excerpt{'s' if total != 1 else ''} "
                    f"({', '.join(sorted({str(i['evidence_type']) for i in items}))}). "
                    f"{YONG_GEE_SUMMARY}"
                ),
                items=items,
                receipts=receipts,
            )
        return sections

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
            {
                "taxon_id": str(row["id"]),
                "display_name": str(row["scientific_name"]),
                "relation": "same_genus",
            }
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


def _str_or_none(value: Any) -> str | None:
    return None if value is None else str(value)


def _clean_excerpt(value: Any) -> tuple[str | None, bool]:
    if value is None:
        return None, False
    lines = [_WS_RE.sub(" ", line).strip() for line in str(value).splitlines()]
    text = "\n".join(line for line in lines if line).strip()
    if not text:
        return None, False
    if len(text) <= MAX_EXCERPT_CHARS:
        return text, False
    cut = text[: MAX_EXCERPT_CHARS - len(TRUNCATION_MARKER)].rstrip()
    return cut + TRUNCATION_MARKER, True


def _federated_receipt(entry: dict[str, Any]) -> EvidenceReceipt:
    row, payload = entry["row"], entry["payload"]
    notes = (
        "Compiled specialist source, not independently verified by Orchid Continuum; "
        f"evidence_type={payload.get('evidence_type')}; "
        f"review_state={payload.get('review_state')}; "
        f"underlying_citation_status={payload.get('underlying_citation_status') or 'unknown'}; "
        f"source_digest={payload.get('source_digest') or 'not recorded'}."
    )
    fields: dict[str, Any] = {
        "source_id": str(row.get("source_table") or YONG_GEE_SOURCE_TABLE),
        "source_name": str(payload.get("source_name") or YONG_GEE_SOURCE_NAME),
        "record_id": _str_or_none(row.get("source_pk")),
        "retrieved_at": row.get("updated_at"),
        "license": None,
        "attribution": YONG_GEE_ATTRIBUTION,
        "evidence_state": DossierEvidenceState.PROVISIONAL,
        # The stored score is source faithfulness, not scientific confidence.
        "confidence": None,
        "notes": notes,
    }
    source_uri = payload.get("source_uri")
    if source_uri:
        try:
            return EvidenceReceipt(**fields, source_url=source_uri)
        except ValueError:
            pass
    return EvidenceReceipt(**fields)
