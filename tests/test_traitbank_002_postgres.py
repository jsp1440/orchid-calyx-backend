"""TRAITBANK-002: supersession, crosswalk, Calyx evidence, Matrix pairwise, literature handoff.

PostgreSQL-backed; same disposable-database contract as
``tests/test_traitbank_postgres.py`` (``TRAITBANK_TEST_DATABASE_URL``; with
``TRAITBANK_REQUIRE_POSTGRES=1`` an unusable database fails instead of
skipping). Records exist only in that database. Darwin (1862) is verbatim; the
other sources are test-scoped and are not evidence.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.literature_extraction.models import PaperKnowledge
from app.traitbank import cli, routes
from app.traitbank.adapters import TraitIndex, from_paper_knowledge
from app.traitbank.handoff import ingest_literature_root
from app.traitbank.models import TraitBankBatch
from app.traitbank.repository import TraitBankRefused, TraitBankRepository
from app.traitbank.service import TraitBankService

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures" / "traitbank"
DSN = os.getenv("TRAITBANK_TEST_DATABASE_URL")
REQUIRED = os.getenv("TRAITBANK_REQUIRE_POSTGRES", "").strip() in {"1", "true", "yes"}
ANGRAECUM, STANHOPEA, PHALAENOPSIS = "990000002", "990000012", "990000022"
DARWIN = "tb:lit:darwin-1862-fertilisation-of-orchids:m-nectary-length"
API_KEY = "traitbank-002-test-key"


def _usable() -> str | None:
    if not DSN:
        return "TRAITBANK_TEST_DATABASE_URL is not configured"
    try:
        with psycopg.connect(DSN, connect_timeout=3) as conn:
            conn.execute("SELECT 1")
    except Exception as exc:  # noqa: BLE001 - reported verbatim as the skip/fail reason
        return f"TraitBank test database unusable: {type(exc).__name__}"
    return None


_REASON = _usable()
if _REASON and REQUIRED:
    pytest.fail(_REASON, pytrace=False)
pytestmark = pytest.mark.skipif(_REASON is not None, reason=_REASON or "")


@pytest.fixture()
def repo() -> TraitBankRepository:
    migrations = [
        (ROOT / "migrations" / name).read_text()
        for name in (
            "20261011_oc_traitbank_v1.sql",
            "20261013_oc_traitbank_v2_supersession.sql",
        )
    ]
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS oc_traitbank CASCADE")
        for sql_text in migrations + migrations:  # second pass proves idempotency
            conn.execute(sql_text)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS public.orchid_taxonomy "
            "(id bigint PRIMARY KEY, scientific_name text NOT NULL, genus text)"
        )
        conn.execute(
            "DELETE FROM public.orchid_taxonomy WHERE id BETWEEN 990000001 AND 990000099"
        )
        conn.execute(
            "INSERT INTO public.orchid_taxonomy (id, scientific_name, genus) VALUES "
            "(%s,'Angraecum sesquipedale','Angraecum'), (%s,'Stanhopea candida','Stanhopea'), "
            "(%s,'Phalaenopsis amabilis','Phalaenopsis')",
            (int(ANGRAECUM), int(STANHOPEA), int(PHALAENOPSIS)),
        )
    repository = TraitBankRepository(DSN)
    repository.load_definitions(cli.load_definition_file())
    return repository


def _paper() -> PaperKnowledge:
    return PaperKnowledge.model_validate_json(
        (FIXTURES / "darwin_1862_paper_knowledge.json").read_text()
    )


def _ingest_darwin(repo: TraitBankRepository) -> None:
    result = from_paper_knowledge(
        _paper(), TraitIndex(repo.definitions()), repo.resolve_species
    )
    repo.ingest(result.batch, ingested_by="ci", crosswalk=result.crosswalk)


def _presence(aid: str, taxon: str, state: str, record: str, confidence=None) -> dict:
    return {
        "assertion_id": aid,
        "trait_id": "oc:trait:spur_presence",
        "level": "taxon",
        "scope_basis": "source_reported",
        "subject": {"taxon_id": taxon, "verbatim_taxon_name": "CI taxon"},
        "value": {"kind": "categorical", "state_id": state, "verbatim": state},
        "evidence_state": "PROVISIONAL",
        "confidence": confidence,
        "provenance": {
            "source_id": f"doi:10.1000/ci-{record}",
            "source_kind": "publication",
            "original_record_id": record,
            "citation": f"CI validation source {record} (disposable test database only).",
            "license": "CC BY 4.0",
            "evidence_type": "literature_reported",
            "original_text": f"spur {state}",
        },
    }


def _curated(key: str, *assertions: dict) -> TraitBankBatch:
    return TraitBankBatch.model_validate(
        {
            "contract_version": "oc-traitbank-v1",
            "batch_key": key,
            "producer": "curated",
            "assertions": list(assertions),
        }
    )


def _supersede(repo, original, successor, kind="corrected", **kw):
    return repo.supersede(
        superseded_assertion_id=original,
        superseding_assertion_id=successor,
        kind=kind,
        reason=kw.get(
            "reason", "Reviewer found the state was transcribed from the wrong figure."
        ),
        review_reference=kw.get("review_reference", "review:ci-0001"),
        decided_by=kw.get("decided_by", "ci-reviewer"),
        dry_run=kw.get("dry_run", False),
    )


def _codes(exc: pytest.ExceptionInfo) -> set[str]:
    return {v["code"] for v in exc.value.violations}


# -- supersession never edits the original ------------------------------------------------


def test_supersession_keeps_the_original_and_changes_only_the_current_view(repo):
    repo.ingest(
        _curated(
            "curated:ci-sup-0001", _presence("tb:cur:old", STANHOPEA, "absent", "R-1")
        ),
        ingested_by="ci",
    )
    repo.ingest(
        _curated(
            "curated:ci-sup-0002", _presence("tb:cur:new", STANHOPEA, "present", "R-2")
        ),
        ingested_by="ci",
    )
    with psycopg.connect(DSN) as conn:
        before = conn.execute(
            "SELECT * FROM oc_traitbank.assertions WHERE assertion_id='tb:cur:old'"
        ).fetchone()
    assert _supersede(repo, "tb:cur:old", "tb:cur:new")["state"] == "RECORDED"
    with psycopg.connect(DSN) as conn:
        after = conn.execute(
            "SELECT * FROM oc_traitbank.assertions WHERE assertion_id='tb:cur:old'"
        ).fetchone()
    assert before == after  # byte-for-byte identical stored row
    service = TraitBankService(repo)
    detail = service.assertion("tb:cur:old")["assertion"]
    assert (
        detail["value"]["state_id"] == "absent"
        and detail["evidence_state"] == "PROVISIONAL"
    )
    assert detail["supersession"]["effective_state"] == "SUPERSEDED"
    assert detail["supersession"]["superseded_by"] == "tb:cur:new"
    assert detail["supersession"]["review_reference"] == "review:ci-0001"
    assert [h["kind"] for h in detail["supersession"]["history"]] == ["corrected"]
    # Current views see only the successor; the original stays queryable.
    (summary,) = service.taxon(STANHOPEA)["traits"]
    assert summary["levels"]["taxon"]["state_counts"] == {"present": 1}
    assert {
        a["assertion_id"]
        for a in service.character("oc:trait:spur_presence")["assertions"]
    } == {"tb:cur:old", "tb:cur:new"}


def test_supersession_resolves_a_conflict_without_deleting_either_side(repo):
    repo.ingest(
        _curated(
            "curated:ci-conf-0001",
            _presence("tb:cur:p", STANHOPEA, "present", "P-1"),
            _presence("tb:cur:a", STANHOPEA, "absent", "A-1"),
        ),
        ingested_by="ci",
    )
    service = TraitBankService(repo)
    assert len(service.conflicts(taxon_id=STANHOPEA)["conflicts"]) == 1
    _supersede(
        repo,
        "tb:cur:a",
        None,
        kind="retracted",
        reason="Source erratum withdrew the absence statement for this species.",
    )
    assert service.conflicts(taxon_id=STANHOPEA)["conflicts"] == []
    assert service.assertion("tb:cur:a")["assertion"]["value"]["state_id"] == "absent"


def test_supersession_rules(repo):
    repo.ingest(
        _curated(
            "curated:ci-rule-0001",
            _presence("tb:cur:s1", STANHOPEA, "present", "S-1"),
            _presence("tb:cur:s2", STANHOPEA, "present", "S-2"),
            _presence("tb:cur:s3", STANHOPEA, "present", "S-3"),
            _presence("tb:cur:p1", PHALAENOPSIS, "absent", "P-9"),
        ),
        ingested_by="ci",
    )
    _ingest_darwin(repo)
    with pytest.raises(TraitBankRefused) as exc:
        _supersede(repo, "tb:cur:s1", None)  # non-retraction needs a successor
    assert "SUCCESSOR_REQUIRED" in _codes(exc)
    with pytest.raises(TraitBankRefused) as exc:
        _supersede(repo, "tb:cur:s1", "tb:cur:s2", kind="retracted")
    assert "RETRACTION_HAS_NO_SUCCESSOR" in _codes(exc)
    with pytest.raises(TraitBankRefused) as exc:
        _supersede(repo, "tb:cur:s1", DARWIN)
    assert "SUCCESSOR_TRAIT_MISMATCH" in _codes(exc)
    with pytest.raises(TraitBankRefused) as exc:
        _supersede(
            repo, "tb:cur:s1", "tb:cur:p1"
        )  # another taxon, not a re-identification
    assert "TAXON_CHANGE_REQUIRES_REIDENTIFIED" in _codes(exc)
    with pytest.raises(TraitBankRefused) as exc:
        _supersede(repo, "tb:cur:s1", "tb:cur:s2", kind="reidentified")
    assert "REIDENTIFIED_REQUIRES_TAXON_CHANGE" in _codes(exc)
    with pytest.raises(TraitBankRefused) as exc:
        # SYNTHETIC open-Atlantic point assembled at runtime; see
        # tests/test_no_precise_coordinates.py. Not a locality of any organism.
        _supersede(
            repo,
            "tb:cur:s1",
            "tb:cur:s2",
            reason="at " + "12." + "3456, -45." + "6789 per grower",
        )
    assert "COORDINATES_REFUSED" in _codes(exc)
    assert (
        _supersede(repo, "tb:cur:s1", "tb:cur:s2", dry_run=True)["state"]
        == "DRY_RUN_OK"
    )
    assert (
        TraitBankService(repo).assertion("tb:cur:s1")["assertion"]["supersession"][
            "superseded_by"
        ]
        is None
    )
    # Linear chains: recorded once, replay is a no-op, a different decision is refused.
    assert _supersede(repo, "tb:cur:s1", "tb:cur:s2")["state"] == "RECORDED"
    assert _supersede(repo, "tb:cur:s1", "tb:cur:s2")["state"] == "ALREADY_RECORDED"
    with pytest.raises(TraitBankRefused) as exc:
        _supersede(repo, "tb:cur:s1", "tb:cur:s3")
    assert "ALREADY_SUPERSEDED" in _codes(exc)
    with pytest.raises(TraitBankRefused) as exc:
        _supersede(repo, "tb:cur:s3", "tb:cur:s1")  # successor is no longer current
    assert "SUCCESSOR_NOT_CURRENT" in _codes(exc)
    _supersede(repo, "tb:cur:s2", "tb:cur:s3", kind="reanalysed")
    history = TraitBankService(repo).assertion("tb:cur:s1")["assertion"][
        "supersession"
    ]["history"]
    assert [
        (h["superseded_assertion_id"], h["superseding_assertion_id"]) for h in history
    ] == [("tb:cur:s1", "tb:cur:s2"), ("tb:cur:s2", "tb:cur:s3")]


def test_supersession_records_are_append_only_and_constrained_in_the_database(repo):
    repo.ingest(
        _curated(
            "curated:ci-db-0001",
            _presence("tb:cur:d1", STANHOPEA, "present", "D-1"),
            _presence("tb:cur:d2", STANHOPEA, "present", "D-2"),
        ),
        ingested_by="ci",
    )
    _supersede(
        repo,
        "tb:cur:d1",
        None,
        kind="retracted",
        reason="Withdrawn by the source in a later erratum.",
    )
    with (
        psycopg.connect(DSN) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        conn.execute("DELETE FROM oc_traitbank.assertion_supersessions")
    with psycopg.connect(DSN) as conn, pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "INSERT INTO oc_traitbank.assertion_supersessions (superseded_assertion_id, superseding_assertion_id, "
            "kind, reason, review_reference, decided_by, record_sha256) VALUES "
            "('tb:cur:d2', 'tb:cur:d1', 'retracted', 'retraction with a successor', 'r', 'x', repeat('0', 64))"
        )


# -- crosswalk, Calyx evidence, Matrix pairwise -----------------------------------------------


def test_crosswalk_identifiers_are_stored_and_served(repo):
    _ingest_darwin(repo)
    ids = TraitBankService(repo).assertion(DARWIN)["assertion"]["identifiers"]
    assert (
        ids["kg_object_key"]
        == "measurement:darwin-1862-fertilisation-of-orchids:m-nectary-length"
    )
    assert (
        ids["source_record_kind"] == "measurement" and ids["taxonomy_id"] == ANGRAECUM
    )
    assert ids["graph_edge_payload"]["qualifier"].startswith("assertion_level=specimen")


def test_calyx_evidence_packet_is_1819_shaped_and_states_its_gaps(repo):
    _ingest_darwin(repo)
    repo.ingest(
        _curated(
            "curated:ci-ev-0001", _presence("tb:cur:e1", ANGRAECUM, "present", "E-1")
        ),
        ingested_by="ci",
    )
    packet = TraitBankService(repo).evidence(ANGRAECUM)
    assert (
        packet["confidence_is_probability"] is False
        and packet["graph_mutation"] is False
    )
    refs = {i["ref"]: i for i in packet["items"]}
    assert (
        refs[f"traitbank:{DARWIN}"]["edge_type"]
        == "has_trait_evidence_from_individuals"
    )
    assert refs["traitbank:tb:cur:e1"]["edge_type"] == "has_trait"
    assert "CONFIDENCE_NOT_REPORTED" in packet["gaps"]
    only_spur_length = TraitBankService(repo).evidence(
        ANGRAECUM, "oc:trait:spur_length"
    )
    assert "NO_TAXON_LEVEL_ASSERTION" in only_spur_length["gaps"]


def test_taxon_graph_node_mapping_uses_the_existing_kg_convention(repo):
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute("CREATE SCHEMA IF NOT EXISTS oc_graph")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS oc_graph.kg_nodes (kg_node_id bigint PRIMARY KEY, node_type text NOT NULL, "
            "canonical_key text NOT NULL, display_label text, source_pk text, is_active boolean DEFAULT true)"
        )
        conn.execute(
            "DELETE FROM oc_graph.kg_nodes WHERE kg_node_id BETWEEN 990000001 AND 990000099"
        )
        conn.execute(
            "INSERT INTO oc_graph.kg_nodes VALUES (990000001, 'taxon', 'taxon:ci-1', 'Angraecum sesquipedale', %s, true)",
            (ANGRAECUM,),
        )
    try:
        _ingest_darwin(repo)
        taxon = TraitBankService(repo).evidence(ANGRAECUM)["taxon"]
        assert taxon["graph_available"] is True
        assert taxon["graph_node"]["canonical_key"] == "taxon:ci-1"
    finally:
        with psycopg.connect(DSN, autocommit=True) as conn:
            conn.execute(
                "DELETE FROM oc_graph.kg_nodes WHERE kg_node_id BETWEEN 990000001 AND 990000099"
            )


def test_pairwise_morphology_compares_species_on_taxon_level_evidence(repo):
    _ingest_darwin(repo)
    repo.ingest(
        _curated(
            "curated:ci-pair-0001",
            _presence("tb:cur:x1", ANGRAECUM, "present", "X-1", confidence=0.9),
            _presence("tb:cur:x2", STANHOPEA, "present", "X-2", confidence=0.7),
        ),
        ingested_by="ci",
    )
    dim = TraitBankService(repo).pairwise(ANGRAECUM, STANHOPEA)["dimension"]
    assert (dim["availability"], dim["score"], dim["confidence"]) == (
        "available",
        1.0,
        0.7,
    )
    assert DARWIN not in dim["provenance"]
    assert any("not used to compare species" in lim for lim in dim["limitations"])


# -- literature-extraction handoff --------------------------------------------------------------


def test_literature_root_handoff_is_bounded_resumable_and_idempotent(
    repo, tmp_path: Path
):
    paper = _paper()
    (tmp_path / paper.paper_id).mkdir()
    (tmp_path / paper.paper_id / "paper.json").write_text(paper.model_dump_json())
    (tmp_path / "zz-broken").mkdir()
    (tmp_path / "zz-broken" / "paper.json").write_text(
        json.dumps({"paper_id": "zz-broken"})
    )
    dry = ingest_literature_root(repo, tmp_path, ingested_by="ci", limit=1)
    assert dry["dry_run"] and dry["processed"] == 1 and dry["remaining"] == 1
    assert dry["papers"][0]["state"] == "DRY_RUN_OK"
    with psycopg.connect(DSN) as conn:
        assert (
            conn.execute("SELECT count(*) FROM oc_traitbank.assertions").fetchone()[0]
            == 0
        )
    applied = ingest_literature_root(repo, tmp_path, ingested_by="ci", apply=True)
    assert applied["states"] == {"INGESTED": 1, "PAPER_INVALID": 1}
    again = ingest_literature_root(repo, tmp_path, ingested_by="ci", apply=True)
    assert again["states"] == {"ALREADY_INGESTED": 1, "PAPER_INVALID": 1}
    resumed = ingest_literature_root(
        repo, tmp_path, ingested_by="ci", after_paper_id=paper.paper_id
    )
    assert [p["paper_id"] for p in resumed["papers"]] == ["zz-broken"]
    ids = TraitBankService(repo).assertion(DARWIN)["assertion"]["identifiers"]
    assert ids["kg_object_key"].startswith("measurement:")


# -- HTTP ----------------------------------------------------------------------------------------


def test_new_routes_are_authenticated_and_read_only(repo, monkeypatch):
    monkeypatch.setenv("CALYX_API_KEY", API_KEY)
    _ingest_darwin(repo)
    app = FastAPI()
    app.include_router(routes.router)
    monkeypatch.setattr(routes, "get_service", lambda: TraitBankService(repo))
    client = TestClient(app, raise_server_exceptions=False)
    assert client.get(f"/api/traitbank/taxa/{ANGRAECUM}/evidence").status_code == 401
    headers = {"X-API-Key": API_KEY}
    assert client.get(
        f"/api/traitbank/taxa/{ANGRAECUM}/evidence", headers=headers
    ).json()["items"]
    pair = client.get(
        f"/api/traitbank/pairwise?subject_taxon_id={ANGRAECUM}&object_taxon_id={STANHOPEA}",
        headers=headers,
    )
    assert (
        pair.status_code == 200
        and pair.json()["dimension"]["dimension"] == "morphology"
    )
    same = client.get(
        f"/api/traitbank/pairwise?subject_taxon_id={ANGRAECUM}&object_taxon_id={ANGRAECUM}",
        headers=headers,
    )
    assert same.status_code == 422
    assert all(route.methods == {"GET"} for route in routes.router.routes)
