"""Release-1 journey 18 — one canonical taxon identity across modules.

One fake ``public.orchid_taxonomy`` / ``public.orchid_images`` / ``oc_graph`` answers
both the homepage species exhibit and the species dossier + federation resolver, so
the test can prove that the same row yields the same ``taxon_id``, the same binomial,
the same provenance anchor and the same Knowledge Graph key everywhere, and that the
observation modules never mint a taxon id from a verbatim name.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
from typing import Any

import pytest

from app.community_observation.models import (
    CommunityObservation,
    ObservationEpistemicLabel,
    ObservationSubmitRequest,
)
from app.field_observation.schemas import FieldObservationCreate, FieldObservationOut
from app.species_dossier.models import FederationResolveRequest
from app.species_dossier.repository import PostgresSpeciesRepository
from app.species_dossier.service import SpeciesDossierService
from app.species_exhibit import service as exhibit_service

TAXA = [
    {"id": 101, "scientific_name": "Phalaenopsis amabilis (L.) Blume", "genus": "Phalaenopsis"},
    {"id": 102, "scientific_name": "Phalaenopsis aphrodite Rchb.f.", "genus": "Phalaenopsis"},
    {"id": 103, "scientific_name": "Dracula vampira (Luer) Luer", "genus": "Dracula"},
]
IMAGES: dict[int, list[dict[str, Any]]] = {
    101: [
        {"id": 9001, "image_url": "https://images.example/1.jpg", "image_source": "iNaturalist", "image_license": "CC-BY-NC-4.0",
         "image_rights_holder": "A. Grower", "observer_name": "A. Grower", "gbif_occurrence_key": None},
    ],
    102: [
        {"id": 9002, "image_url": "https://images.example/2.jpg", "image_source": "Wikimedia Commons", "image_license": "CC-BY-SA-4.0",
         "image_rights_holder": None, "observer_name": "B. Photographer", "gbif_occurrence_key": None},
    ],
}
GRAPH: dict[int, list[dict[str, Any]]] = {
    101: [
        {"edge_type": "pollinated_by", "node_type": "pollinator", "canonical_key": "pollinator:moth", "display_label": "hawk moth",
         "evidence_class": "literature", "confidence_score": 0.7, "confidence_label": "moderate", "source_table": "oc_graph.kg_edges", "source_pk": 5},
    ]
}


class SharedTaxonomyCursor:
    """Answers the exact SQL shapes both modules issue; anything else fails the test."""

    def __init__(self) -> None:
        self._rows: list[dict[str, Any]] = []
        self.graph_keys: list[str] = []

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        compact = " ".join(sql.split())
        if "to_regclass('oc_graph.kg_nodes')" in compact:
            self._rows = [{"nodes_present": True, "edges_present": True}]
        elif "FROM public.orchid_taxonomy t LEFT JOIN public.orchid_images i" in compact:  # exhibit genus listing
            genus = params[0].lower()
            self._rows = [
                {**t, "image_count": len(IMAGES.get(t["id"], []))} for t in TAXA if t["genus"].lower() == genus
            ][: params[1]]
        elif "FROM public.orchid_taxonomy WHERE id::text = %s" in compact:  # dossier taxon
            self._rows = [dict(t) for t in TAXA if str(t["id"]) == params[0]]
        elif "lower(scientific_name) = lower(%s)" in compact:  # resolver
            wanted = params[0].lower()
            self._rows = [
                dict(t) for t in TAXA
                if t["scientific_name"].lower() == wanted or " ".join(t["scientific_name"].split()[:2]).lower() == wanted
            ]
        elif "FROM public.orchid_images" in compact:  # both modules: media for one taxonomy_id
            self._rows = list(IMAGES.get(int(params[0]), []))
        elif "FROM oc_graph.kg_nodes n1" in compact:  # both modules: outgoing graph edges
            self.graph_keys.append(params[0])
            self._rows = list(GRAPH.get(int(params[0].split(":", 1)[1]), []))
        elif "lower(genus) = lower(%s) AND id::text <> %s" in compact:  # dossier related species
            self._rows = [dict(t) for t in TAXA if t["genus"].lower() == params[0].lower() and str(t["id"]) != params[1]]
        else:  # pragma: no cover
            raise AssertionError(f"unexpected SQL: {compact}")

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    # exhibit opens the cursor as a context manager
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConnection:
    def __init__(self, cursor: SharedTaxonomyCursor) -> None:
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture()
def shared():
    cursor = SharedTaxonomyCursor()
    repository = PostgresSpeciesRepository(lambda work: work(cursor))
    service = SpeciesDossierService(repository, public_base_url="https://oc.test")
    return cursor, repository, service


@pytest.fixture()
def exhibit(shared, monkeypatch):
    cursor, _, _ = shared

    @contextmanager
    def fake_connect(dsn, **kwargs):
        yield FakeConnection(cursor)

    monkeypatch.setattr(exhibit_service.psycopg, "connect", fake_connect)
    return exhibit_service.build_species_exhibit("postgresql://fake", "Phalaenopsis", limit=9)


def card(exhibit: dict[str, Any], taxon_id: str) -> dict[str, Any]:
    return next(item for item in exhibit["items"] if item["taxon_id"] == taxon_id)


# -- one row, one identity ----------------------------------------------------------------


def test_exhibit_dossier_and_resolver_agree_on_taxon_id_and_binomial_for_the_same_row(shared, exhibit):
    _, repository, service = shared
    dossier = repository.get_dossier("101")
    assert dossier is not None
    exhibit_card = card(exhibit, "101")

    assert exhibit_card["taxon_id"] == dossier.identity.taxon_id == "101"
    assert exhibit_card["display_name"] == dossier.identity.display_name == dossier.identity.accepted_name == "Phalaenopsis amabilis"
    assert exhibit_card["full_scientific_name"] == dossier.identity.full_scientific_name == "Phalaenopsis amabilis (L.) Blume"
    assert exhibit_card["evidence_states"]["identity"]["value"]["authorship"] == dossier.identity.authorship == "(L.) Blume"
    assert exhibit_card["evidence_states"]["identity"]["value"]["genus"] == dossier.identity.genus == "Phalaenopsis"

    # The binomial shown on the exhibit resolves back to the very same taxon through federation.
    resolved = service.resolve(FederationResolveRequest(name=exhibit_card["display_name"]))
    assert (resolved.status, resolved.taxon_id, resolved.matched_name) == ("resolved", "101", "Phalaenopsis amabilis")
    assert resolved.canonical_dossier_url == "https://oc.test/species/101"
    # ...and so does the exhibit's own continuation link target.
    assert exhibit_card["links"]["species"] == "/species/101"


def test_both_modules_anchor_provenance_on_the_same_taxonomy_record(shared, exhibit):
    _, repository, _ = shared
    dossier = repository.get_dossier("101")
    taxonomy_receipts = [r for r in dossier.provenance if r.source_id == "public.orchid_taxonomy"]
    assert [r.record_id for r in taxonomy_receipts] == ["101"]

    anchors = card(exhibit, "101")["provenance"]
    assert {"kind": "taxonomy", "source": "public.orchid_taxonomy", "record_id": "101"} in anchors


def test_both_modules_read_the_knowledge_graph_under_one_canonical_key(shared, exhibit):
    cursor, repository, _ = shared
    keys_after_exhibit = list(cursor.graph_keys)
    assert "taxon:101" in keys_after_exhibit and "taxon:102" in keys_after_exhibit
    repository.get_dossier("101")
    assert cursor.graph_keys[len(keys_after_exhibit):] == ["taxon:101"]

    dossier = repository.get_dossier("101")
    assert dossier.knowledge_graph.items[0]["canonical_key"] == "pollinator:moth"
    assert card(exhibit, "101")["evidence_states"]["knowledge_graph"]["value"][0]["canonical_key"] == "pollinator:moth"


def test_related_species_ids_are_the_exhibit_s_taxon_ids_for_the_genus(shared, exhibit):
    _, repository, _ = shared
    dossier = repository.get_dossier("101")
    related_ids = {item["taxon_id"] for item in dossier.related_species}
    exhibit_ids = {item["taxon_id"] for item in exhibit["items"]}
    assert related_ids == {"102"}
    assert related_ids < exhibit_ids
    assert exhibit["distinct_taxa"] == len(exhibit_ids) == 2


def test_media_rows_are_attributed_to_the_same_taxonomy_id_in_both_modules(shared, exhibit):
    _, repository, _ = shared
    dossier = repository.get_dossier("102")
    assert [item["url"] for item in dossier.living_media.items] == ["https://images.example/2.jpg"]
    exhibit_media = card(exhibit, "102")["evidence_states"]["media"]["value"]
    assert exhibit_media["url"] == "https://images.example/2.jpg"
    assert exhibit_media["id"] == 9002 == int(dossier.living_media.receipts[0].record_id)
    # Both modules label a source image the same way: a record, not an independent identification.
    assert exhibit_media["identification_state"] == dossier.living_media.items[0]["identification_state"]
    assert exhibit_media["identification_state"] == "source_record_not_independently_verified"


# -- observations never mint a taxon identity ---------------------------------------------


def test_field_observations_carry_a_taxon_hint_and_refuse_a_caller_supplied_taxon_id():
    assert "taxon_id" not in FieldObservationOut.model_fields
    assert "taxon_hint" in FieldObservationOut.model_fields
    with pytest.raises(ValueError):
        FieldObservationCreate(observed_at=datetime.now(tz=timezone.utc), note="seen", taxon_hint="Dracula vampira", taxon_id="103")


def test_community_observations_keep_the_verbatim_name_and_never_gain_a_taxon_id():
    assert "taxon_id" not in CommunityObservation.model_fields
    request = ObservationSubmitRequest.model_validate(
        {
            "taxon_name_verbatim": "Dracula vampira",
            "location_verbatim": "withheld",
            "observation_date": str(date(2026, 8, 2)),
            "epistemic_label": "PROBABLE",
            "taxon_id": "103",  # a caller cannot pre-determine the taxon
        }
    )
    assert "taxon_id" not in request.model_dump()
    observation = CommunityObservation(
        submitter_auth_subject="s",
        taxon_name_verbatim=request.taxon_name_verbatim,
        location_verbatim=request.location_verbatim,
        observation_date=request.observation_date,
        epistemic_label=ObservationEpistemicLabel.PROBABLE,
    )
    assert "taxon_id" not in observation.model_dump()
    assert observation.taxon_name_verbatim == "Dracula vampira"


def test_a_verbatim_observer_name_is_resolved_only_through_federation_and_never_promoted(shared):
    _, _, service = shared
    resolved = service.resolve(FederationResolveRequest(name="Dracula vampira"))
    assert (resolved.status, resolved.taxon_id, resolved.match_state) == ("resolved", "103", "accepted_name")
    unresolved = service.resolve(FederationResolveRequest(name="Dracula vampyra"))  # observer misspelling
    assert unresolved.status == "unresolved" and unresolved.taxon_id is None
