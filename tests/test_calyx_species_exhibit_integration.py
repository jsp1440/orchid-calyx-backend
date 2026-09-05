"""Real service->SQL->PostgreSQL integration test for the Species Exhibit.

The existing ``test_calyx_species_exhibit_contract`` suite exercises the pure
card-shaping helpers with in-memory dicts. Nothing exercised
``build_species_exhibit`` against an actual database, so the SQL, the
duplicate-image exclusion, the persisted-graph caption/confidence path, and the
fail-closed empty-genus behaviour were never covered end to end.

This test seeds a disposable PostgreSQL with real Phalaenopsis taxa, real image
rows carrying source/license/rights provenance, and one source-bound Knowledge
Graph edge, then asserts the governed contract on the live query path:

* positive evidence is returned with provenance anchors and an evidence receipt;
* a species-specific caption/fact appears ONLY when a persisted graph edge backs
  it -- it is never fabricated for taxa without an edge;
* confidence is taken only from a persisted edge score;
* unavailable domains and imageless taxa are reported honestly, not as zero;
* a duplicate image row is excluded from the representative media choice;
* an unknown genus returns zero items and never fabricates completeness.

Gating: this test only runs when ``CALYX_SPECIES_EXHIBIT_TEST_DSN`` points at a
reachable, DISPOSABLE database. It deliberately does NOT use ``DATABASE_URL`` /
``TEST_DATABASE_URL`` so it can never seed over a shared validation database, and
it refuses to run (skips) if the canonical tables already exist, then drops only
the objects it created.
"""

from __future__ import annotations

import os
import socket
from urllib.parse import urlparse

import pytest

psycopg = pytest.importorskip("psycopg")
from psycopg.rows import dict_row

from app.species_exhibit.service import build_species_exhibit

DSN = os.getenv("CALYX_SPECIES_EXHIBIT_TEST_DSN")


def _postgres_reachable(dsn: str | None, timeout: float = 0.5) -> bool:
    if not dsn:
        return False
    try:
        parsed = urlparse(dsn)
        with socket.create_connection(
            (parsed.hostname or "localhost", parsed.port or 5432), timeout=timeout
        ):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _postgres_reachable(DSN),
    reason="CALYX_SPECIES_EXHIBIT_TEST_DSN is not set to a reachable disposable PostgreSQL",
)

_FIXTURE_SQL = """
CREATE SCHEMA IF NOT EXISTS oc_graph;
CREATE TABLE public.orchid_taxonomy (
  id bigint PRIMARY KEY, scientific_name text NOT NULL, genus text NOT NULL
);
CREATE TABLE public.orchid_images (
  id bigint PRIMARY KEY, taxonomy_id bigint REFERENCES public.orchid_taxonomy(id),
  image_url text, image_source text, image_license text, image_rights_holder text,
  observer_name text, gbif_occurrence_key text, is_duplicate boolean DEFAULT false
);
CREATE TABLE oc_graph.kg_nodes (
  kg_node_id bigint PRIMARY KEY, canonical_key text UNIQUE NOT NULL,
  node_type text NOT NULL, display_label text
);
CREATE TABLE oc_graph.kg_edges (
  kg_edge_id bigint PRIMARY KEY,
  from_node_id bigint REFERENCES oc_graph.kg_nodes(kg_node_id),
  to_node_id bigint REFERENCES oc_graph.kg_nodes(kg_node_id),
  edge_type text, evidence_class text, confidence_score numeric,
  confidence_label text, source_table text, source_pk text
);

INSERT INTO public.orchid_taxonomy(id, scientific_name, genus) VALUES
 (1001, 'Phalaenopsis amabilis (L.) Blume', 'Phalaenopsis'),
 (1002, 'Phalaenopsis schilleriana Rchb.f.', 'Phalaenopsis'),
 (1003, 'Phalaenopsis aphrodite Rchb.f.', 'Phalaenopsis'),
 (1004, 'Phalaenopsis sanderiana Rchb.f.', 'Phalaenopsis');

INSERT INTO public.orchid_images
 (id, taxonomy_id, image_url, image_source, image_license, image_rights_holder,
  observer_name, gbif_occurrence_key, is_duplicate) VALUES
 (9001, 1001, 'https://inaturalist-open-data.s3.amazonaws.com/photos/amabilis_1.jpg',
  'iNaturalist', 'CC-BY-NC', 'Jane Botanist', 'Jane Botanist', 'gbif-4501001', false),
 (9002, 1001, 'https://inaturalist-open-data.s3.amazonaws.com/photos/amabilis_dup.jpg',
  'iNaturalist', 'CC-BY-NC', 'Jane Botanist', 'Jane Botanist', 'gbif-4501001', true),
 (9003, 1002, 'https://api.gbif.org/v1/image/schilleriana_1.jpg',
  'GBIF', 'CC-BY', 'Herbarium X', NULL, 'gbif-4502002', false),
 (9004, 1003, 'https://inaturalist-open-data.s3.amazonaws.com/photos/aphrodite_1.jpg',
  'iNaturalist', 'CC0', 'Alex Grower', 'Alex Grower', 'gbif-4503003', false);

INSERT INTO oc_graph.kg_nodes(kg_node_id, canonical_key, node_type, display_label) VALUES
 (1, 'taxon:1001', 'taxon', 'Phalaenopsis amabilis'),
 (2, 'trait:growth_habit=epiphytic', 'trait', 'epiphytic growth habit');
INSERT INTO oc_graph.kg_edges
 (kg_edge_id, from_node_id, to_node_id, edge_type, evidence_class,
  confidence_score, confidence_label, source_table, source_pk) VALUES
 (1, 1, 2, 'has_trait', 'literature', 0.88, 'high', 'public.orchid_traits', 'trait-amabilis-1');
"""

_TEARDOWN_SQL = """
DROP TABLE IF EXISTS oc_graph.kg_edges CASCADE;
DROP TABLE IF EXISTS oc_graph.kg_nodes CASCADE;
DROP TABLE IF EXISTS public.orchid_images CASCADE;
DROP TABLE IF EXISTS public.orchid_taxonomy CASCADE;
"""


@pytest.fixture(scope="module")
def seeded_dsn():
    with (
        psycopg.connect(DSN, row_factory=dict_row, autocommit=True) as conn,
        conn.cursor() as cur,
    ):
        cur.execute(
                "SELECT to_regclass('public.orchid_taxonomy') AS a, "
                "to_regclass('public.orchid_images') AS b"
            )
        existing = cur.fetchone()
        if existing and (existing["a"] or existing["b"]):
            pytest.skip(
                "canonical orchid tables already exist on target DSN; refusing to "
                "seed over a non-disposable database"
            )
        cur.execute(_FIXTURE_SQL)
    try:
        yield DSN
    finally:
        with (
            psycopg.connect(DSN, autocommit=True) as conn,
            conn.cursor() as cur,
        ):
            cur.execute(_TEARDOWN_SQL)


def _by_name(result, needle):
    return next(it for it in result["items"] if needle in it["full_scientific_name"])


def test_exhibit_returns_provenance_bearing_cards(seeded_dsn):
    result = build_species_exhibit(seeded_dsn, "Phalaenopsis", limit=9)
    assert result["contract"] == "calyx-species-exhibit-v1"
    assert result["publication_authority"] is False
    assert result["graph_mutation"] is False
    assert result["count"] == 4
    assert result["distinct_taxa"] == 4

    amabilis = _by_name(result, "amabilis")
    # duplicate image row (is_duplicate=true) must be excluded from the choice
    assert amabilis["representative_media"]["url"].endswith("amabilis_1.jpg")
    assert amabilis["representative_media"]["license"] == "CC-BY-NC"
    assert amabilis["representative_media"]["source"] == "iNaturalist"
    assert amabilis["representative_media"]["rights_holder"] == "Jane Botanist"
    assert {a["kind"] for a in amabilis["provenance"]} == {
        "taxonomy",
        "media",
        "knowledge_graph",
    }
    assert amabilis["evidence_receipt"]["algorithm"] == "sha256"
    assert amabilis["evidence_receipt"]["contents_included"] is False


def test_persisted_graph_edge_drives_caption_and_confidence(seeded_dsn):
    result = build_species_exhibit(seeded_dsn, "Phalaenopsis", limit=9)
    amabilis = _by_name(result, "amabilis")
    # caption/fact is present because a persisted edge backs it
    assert amabilis["caption"] == "Phalaenopsis amabilis: has trait — epiphytic growth habit."
    assert amabilis["distinguishing_fact"] == (
        "Phalaenopsis amabilis — has trait: epiphytic growth habit"
    )
    assert amabilis["evidence_state"] == "available"
    assert amabilis["confidence"]["state"] == "available"
    assert abs(float(amabilis["confidence"]["score"]) - 0.88) < 1e-9
    assert amabilis["distinguishing_fact_provenance"]["source_table"] == "public.orchid_traits"


def test_no_edge_never_fabricates_species_claim(seeded_dsn):
    result = build_species_exhibit(seeded_dsn, "Phalaenopsis", limit=9)
    schilleriana = _by_name(result, "schilleriana")
    # image present, but no persisted graph edge -> no fabricated caption/fact
    assert schilleriana["representative_media"] is not None
    assert schilleriana["caption"] is None
    assert schilleriana["distinguishing_fact"] is None
    assert schilleriana["confidence"]["state"] == "unavailable"
    assert schilleriana["evidence_state"] == "provisional"
    assert "knowledge_graph" in schilleriana["unavailable_domains"]


def test_imageless_taxon_reports_media_unavailable_not_zero(seeded_dsn):
    result = build_species_exhibit(seeded_dsn, "Phalaenopsis", limit=9)
    sanderiana = _by_name(result, "sanderiana")
    assert sanderiana["representative_media"] is None
    assert sanderiana["image_count"] == 0
    assert "media" in sanderiana["unavailable_domains"]
    assert any("representative image" in c for c in sanderiana["caveats"])


def test_unknown_genus_fails_closed(seeded_dsn):
    result = build_species_exhibit(seeded_dsn, "Dracula", limit=9)
    assert result["count"] == 0
    assert result["items"] == []
    assert result["distinct_taxa"] == 0
    assert result["publication_authority"] is False
    assert result["graph_mutation"] is False
