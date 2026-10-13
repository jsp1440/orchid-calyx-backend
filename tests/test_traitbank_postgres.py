"""TRAITBANK-001: PostgreSQL-backed integration tests.

Needs a disposable database in ``TRAITBANK_TEST_DATABASE_URL``. The tests drop
and recreate the ``oc_traitbank`` schema and add canonical taxonomy rows in a
reserved id range (990000001-990000099); never point this at a database whose
contents matter. Without the variable the module skips, unless
``TRAITBANK_REQUIRE_POSTGRES=1`` (set by the TraitBank workflow), in which case
an absent or unusable database is a failure, not a skip.

The records ingested here exist only in that disposable database. Darwin (1862)
is quoted verbatim; the other sources are test-scoped and are not evidence.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.candidate_knowledge.repository import MemoryCandidateRepository
from app.candidate_knowledge.service import CandidateExtractionService
from app.literature_extraction.models import PaperKnowledge
from app.parallel_platform.brain_candidate_handoff import handoff_brain_candidate
from app.traitbank import cli, routes
from app.traitbank.adapters import TraitIndex, from_paper_knowledge
from app.traitbank.models import TraitBankBatch, TraitDefinitionIn
from app.traitbank.repository import TraitBankRefused, TraitBankRepository
from app.traitbank.service import TraitBankService

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures" / "traitbank"
DSN = os.getenv("TRAITBANK_TEST_DATABASE_URL")
REQUIRED = os.getenv("TRAITBANK_REQUIRE_POSTGRES", "").strip() in {"1", "true", "yes"}
ANGRAECUM, STANHOPEA, PHALAENOPSIS = "990000002", "990000012", "990000022"
API_KEY = "traitbank-test-key"


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
    migration = "\n".join(
        (ROOT / "migrations" / name).read_text()
        for name in (
            "20261011_oc_traitbank_v1.sql",
            "20261013_oc_traitbank_v2_supersession.sql",
        )
    )
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS oc_traitbank CASCADE")
        conn.execute(migration)
        conn.execute(migration)  # re-running the migration is a no-op
        conn.execute(
            "CREATE TABLE IF NOT EXISTS public.orchid_taxonomy (id bigint PRIMARY KEY, scientific_name text NOT NULL, genus text)"
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


def _darwin_batch(repo: TraitBankRepository) -> TraitBankBatch:
    result = from_paper_knowledge(
        _paper(), TraitIndex(repo.definitions()), repo.resolve_species
    )
    assert result.unmapped == []
    return result.batch


def _curated(batch_key: str, *assertions: dict) -> TraitBankBatch:
    return TraitBankBatch.model_validate(
        {
            "contract_version": "oc-traitbank-v1",
            "batch_key": batch_key,
            "producer": "curated",
            "assertions": list(assertions),
        }
    )


def _spur_presence(
    assertion_id: str, state: str, source_id: str, record_id: str, confidence=None
) -> dict:
    return {
        "assertion_id": assertion_id,
        "trait_id": "oc:trait:spur_presence",
        "level": "taxon",
        "scope_basis": "source_reported",
        "subject": {"taxon_id": STANHOPEA, "verbatim_taxon_name": "Stanhopea candida"},
        "value": {"kind": "categorical", "state_id": state, "verbatim": state},
        "evidence_state": "PROVISIONAL",
        "confidence": confidence,
        "provenance": {
            "source_id": source_id,
            "source_kind": "publication",
            "original_record_id": record_id,
            "citation": f"CI validation source {source_id} (disposable test database only).",
            "license": "CC BY 4.0",
            "evidence_type": "literature_reported",
            "original_text": f"spur {state}",
        },
    }


def _table_count(table: str) -> int:
    with psycopg.connect(DSN) as conn:
        return conn.execute(f"SELECT count(*) FROM oc_traitbank.{table}").fetchone()[0]


# -- persistence, idempotency and duplicate protection -----------------------------------


def test_definitions_are_idempotent_and_immutable(repo):
    again = repo.load_definitions(cli.load_definition_file())
    assert again["inserted"] == [] and "oc:trait:spur_length" in again["unchanged"]
    changed = cli.load_definition_file()[0].model_copy(update={"label": "Renamed"})
    with pytest.raises(TraitBankRefused) as exc:
        repo.load_definitions([TraitDefinitionIn.model_validate(changed.model_dump())])
    assert exc.value.violations[0]["code"] == "DEFINITION_CHANGED_REQUIRES_NEW_TRAIT_ID"


def test_end_to_end_source_to_storage_to_query_to_projection(repo):
    # source evidence -> extraction/normalization
    batch = _darwin_batch(repo)
    # -> TraitBank storage
    report = repo.ingest(batch, ingested_by="ci")
    assert report["state"] == "INGESTED" and len(report["inserted_assertions"]) == 1
    service = TraitBankService(repo)
    # -> query: the original measurement, unit, citation and level are intact
    stored = service.assertion(
        "tb:lit:darwin-1862-fertilisation-of-orchids:m-nectary-length"
    )["assertion"]
    assert (
        stored["level"] == "specimen"
        and stored["subject"]["specimen_id"] == "darwin-1862:flowers-examined"
    )
    assert stored["value"]["numeric"] == 292.1 and stored["value"]["unit"] == "mm"
    assert stored["value"]["verbatim"] == "eleven and a half inches"
    assert (
        stored["provenance"]["original_text"]
        == "nectaries eleven and a half inches long"
    )
    assert (
        "Darwin" in stored["provenance"]["citation"]
        and stored["provenance"]["license"] == "public domain"
    )
    assert stored["storage"]["batch_key"] == batch.batch_key
    taxon = service.taxon(ANGRAECUM)
    assert taxon["taxon"]["name"] == "Angraecum sesquipedale"
    (summary,) = taxon["traits"]
    assert "taxon" not in summary["levels"] and summary["caveats"]
    assert summary["environment_relations"][0]["claim_kind"] == "proposed_hypothesis"
    assert service.species("Angraecum sesquipedale")["taxon"]["taxon_id"] == ANGRAECUM
    assert service.genus("Angraecum")["taxa"][0]["assertion_counts"] == {
        "oc:trait:spur_length": 1
    }
    assert service.source("paper:darwin-1862-fertilisation-of-orchids")["citations"]
    # -> Calyx projection, without overstating
    calyx = service.calyx(ANGRAECUM, "oc:trait:spur_length")
    candidate = calyx["reasoning_envelope"]["candidate_knowledge"]
    assert (
        candidate["predicate"] == "has_trait_evidence_from_individuals"
        and candidate["confidence"] == 0.95
    )
    assert "must not be presented as typical of the species" in calyx["statement"]
    assert "not been verified by a reviewer" in calyx["statement"]
    (request,) = calyx["candidate_handoff"]["requests"]
    assert (
        request["source_object_type"] == "oc_traitbank.assertion"
        and request["source_object_id"] > 0
    )
    components = (mem := MemoryCandidateRepository(), CandidateExtractionService(mem))
    from app.parallel_platform.brain_candidate_handoff import (
        BrainCandidateHandoffRequest,
    )

    handoff = handoff_brain_candidate(
        BrainCandidateHandoffRequest.model_validate(request), components
    )
    assert handoff["review_required"] is True and handoff["graph_mutation"] is False
    # -> Matrix projection, through the existing builder
    matrix = service.matrix([ANGRAECUM])
    assert {a["dimension"] for a in matrix["assertions"]} == {
        "trait_individual_evidence"
    }
    assert (
        matrix["matrices"]["trait_individual_evidence"]["cells"][0]["state"]
        == "present"
    )


def test_same_batch_twice_is_a_no_op_and_a_reused_key_is_refused(repo):
    batch = _darwin_batch(repo)
    first = repo.ingest(batch, ingested_by="ci")
    second = repo.ingest(batch, ingested_by="ci")
    assert (
        second["state"] == "ALREADY_INGESTED"
        and second["batch_pk"] == first["batch_pk"]
    )
    assert _table_count("assertions") == 1
    tampered = TraitBankBatch.model_validate(
        {**batch.model_dump(mode="json"), "environment_relations": []}
    )
    with pytest.raises(TraitBankRefused) as exc:
        repo.ingest(tampered, ingested_by="ci")
    assert exc.value.violations[0]["code"] == "BATCH_KEY_REUSED_WITH_DIFFERENT_PAYLOAD"


def test_duplicate_source_records_are_skipped_or_refused_never_overwritten(repo):
    a = _spur_presence("tb:cur:stanhopea-1", "present", "doi:10.1000/ci-a", "A-1")
    repo.ingest(_curated("curated:ci-dup-0001", a), ingested_by="ci")
    again = repo.ingest(_curated("curated:ci-dup-0002", a), ingested_by="ci")
    assert (
        again["skipped_identical_assertions"] == ["tb:cur:stanhopea-1"]
        and again["inserted_assertions"] == []
    )
    altered = {
        **a,
        "assertion_id": "tb:cur:stanhopea-1b",
        "value": {"kind": "categorical", "state_id": "absent"},
    }
    with pytest.raises(TraitBankRefused) as exc:
        repo.ingest(_curated("curated:ci-dup-0003", altered), ingested_by="ci")
    assert (
        exc.value.violations[0]["code"]
        == "SOURCE_RECORD_CONFLICTS_WITH_STORED_ASSERTION"
    )
    assert (
        TraitBankService(repo).assertion("tb:cur:stanhopea-1")["assertion"]["value"][
            "state_id"
        ]
        == "present"
    )


def test_dry_run_checks_everything_and_writes_nothing(repo):
    report = repo.ingest(_darwin_batch(repo), ingested_by="ci", dry_run=True)
    assert report["state"] == "DRY_RUN_OK" and report["inserted_assertions"]
    assert _table_count("assertions") == 0 and _table_count("ingestion_batches") == 0


def test_stored_records_are_append_only(repo):
    repo.ingest(_darwin_batch(repo), ingested_by="ci")
    with (
        psycopg.connect(DSN) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        conn.execute("UPDATE oc_traitbank.assertions SET numeric_value = 1")
    with (
        psycopg.connect(DSN) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        conn.execute("DELETE FROM oc_traitbank.assertions")


# -- canonical identity, placeholders, provenance --------------------------------------------


def test_non_canonical_taxa_and_unknown_traits_are_refused(repo):
    unknown_taxon = _spur_presence("tb:cur:x", "present", "doi:10.1000/ci-a", "A-9")
    unknown_taxon["subject"]["taxon_id"] = "990000098"
    unknown_trait = {
        **_spur_presence("tb:cur:y", "present", "doi:10.1000/ci-a", "A-8"),
        "trait_id": "oc:trait:column_width",
    }
    with pytest.raises(TraitBankRefused) as exc:
        repo.ingest(
            _curated("curated:ci-ref-0001", unknown_taxon, unknown_trait),
            ingested_by="ci",
        )
    codes = {v["code"] for v in exc.value.violations}
    assert codes == {"TAXON_NOT_IN_CANONICAL_TAXONOMY", "UNKNOWN_TRAIT_ID"}
    assert _table_count("assertions") == 0


def test_brain_fixture_records_cannot_enter_live_storage(repo):
    brain_fixture = _spur_presence(
        "tb:eol:FX-EOL-0003",
        "absent",
        "eol-traitbank:resource:fx-res-11",
        "FX-EOL-0003",
    )
    brain_fixture["provenance"].update(
        fixture_status="synthetic_contract_fixture",
        source_url="https://example.org/oc-fixture/resource/11",
    )
    with pytest.raises(TraitBankRefused) as exc:
        repo.ingest(_curated("curated:ci-fx-0001", brain_fixture), ingested_by="ci")
    codes = {v["code"] for v in exc.value.violations}
    assert {"FIXTURE_RECORD_REFUSED_IN_LIVE", "PLACEHOLDER_REFUSED_IN_LIVE"} <= codes
    # The CLI cannot write in fixture mode at all.
    path = FIXTURES.parent.parent / ".traitbank_fixture_batch.json"
    try:
        path.write_text(
            json.dumps(
                _curated("curated:ci-fx-0002", brain_fixture).model_dump(mode="json")
            )
        )
        with pytest.raises(SystemExit):
            cli.main(
                [
                    "--database-url",
                    DSN,
                    "ingest",
                    str(path),
                    "--fixture-mode",
                    "--apply",
                    "--ingested-by",
                    "ci",
                ]
            )
    finally:
        path.unlink(missing_ok=True)
    assert _table_count("assertions") == 0


def test_missing_confidence_is_stored_as_null_and_reported_unknown(repo):
    repo.ingest(
        _curated(
            "curated:ci-conf-0001",
            _spur_presence("tb:cur:c1", "present", "doi:10.1000/ci-a", "C-1"),
        ),
        ingested_by="ci",
    )
    with psycopg.connect(DSN) as conn:
        assert (
            conn.execute("SELECT confidence FROM oc_traitbank.assertions").fetchone()[0]
            is None
        )
    calyx = TraitBankService(repo).calyx(STANHOPEA, "oc:trait:spur_presence")
    assert calyx["confidence"] is None and calyx["confidence_state"] == "unknown"
    assert calyx["reasoning_envelope"]["candidate_knowledge"]["confidence"] is None
    assert calyx["candidate_handoff"]["requests"] == []
    assert calyx["candidate_handoff"]["withheld"] == [
        {"assertion_id": "tb:cur:c1", "reason": "CONFIDENCE_NOT_REPORTED_NOT_DEFAULTED"}
    ]


def test_conflicting_sources_are_stored_and_reported_not_collapsed(repo):
    repo.ingest(
        _curated(
            "curated:ci-conflict-0001",
            _spur_presence(
                "tb:cur:s-present", "present", "doi:10.1000/ci-a", "P-1", confidence=0.8
            ),
            _spur_presence(
                "tb:cur:s-absent", "absent", "doi:10.1000/ci-b", "Q-1", confidence=0.7
            ),
        ),
        ingested_by="ci",
    )
    service = TraitBankService(repo)
    (conflict,) = service.conflicts(taxon_id=STANHOPEA)["conflicts"]
    assert conflict["assertion_ids"] == ["tb:cur:s-absent", "tb:cur:s-present"]
    assert conflict["resolution"] == "preserved_not_collapsed"
    calyx = service.calyx(STANHOPEA, "oc:trait:spur_presence")
    assert (
        calyx["reasoning_envelope"]["candidate_knowledge"]["review_state"]
        == "review_required"
    )
    assert len(calyx["reasoning_envelope"]["contradictions"]) == 2
    states = {
        a["object_label"]: a["state"] for a in service.matrix([STANHOPEA])["assertions"]
    }
    assert states == {
        "Spur presence: present": "conflicting",
        "Spur presence: absent": "conflicting",
    }
    character = service.character("oc:trait:spur_presence")
    assert (
        len(character["assertions"]) == 2
        and character["definition"]["oao_character_id"] == "OAO:0000042"
    )


def test_privacy_guard_blocks_coordinates_before_any_write(repo):
    leaky = _spur_presence("tb:cur:leak", "present", "doi:10.1000/ci-a", "L-1")
    # SYNTHETIC open-Atlantic point, assembled at runtime (see
    # tests/test_no_precise_coordinates.py); not a locality of any organism.
    leaky["provenance"]["original_text"] = (
        "plant at " + "12." + "3456, -45." + "6789" + " with spur"
    )
    with pytest.raises(TraitBankRefused) as exc:
        repo.ingest(_curated("curated:ci-privacy-0001", leaky), ingested_by="ci")
    assert exc.value.violations[0]["code"] == "COORDINATES_REFUSED"
    assert _table_count("assertions") == 0


# -- HTTP: read-only, authenticated ---------------------------------------------------------


@pytest.fixture()
def client(repo, monkeypatch):
    monkeypatch.setenv("CALYX_API_KEY", API_KEY)
    repo.ingest(_darwin_batch(repo), ingested_by="ci")
    app = FastAPI()
    app.include_router(routes.router)
    monkeypatch.setattr(routes, "get_service", lambda: TraitBankService(repo))
    return TestClient(app, raise_server_exceptions=False)


def test_routes_require_authentication_and_serve_reads(client):
    assert client.get(f"/api/traitbank/taxa/{ANGRAECUM}").status_code == 401
    headers = {"X-API-Key": API_KEY}
    taxon = client.get(f"/api/traitbank/taxa/{ANGRAECUM}", headers=headers)
    assert taxon.status_code == 200 and taxon.json()["state"] == "AVAILABLE"
    evidence = client.get(
        "/api/traitbank/assertions/tb:lit:darwin-1862-fertilisation-of-orchids:m-nectary-length",
        headers=headers,
    ).json()
    assert (
        evidence["assertion"]["provenance"]["original_record_id"] == "m-nectary-length"
    )
    calyx = client.get(
        f"/api/traitbank/taxa/{ANGRAECUM}/calyx/oc:trait:spur_length", headers=headers
    ).json()
    assert calyx["reasoning_envelope"]["human_review_required"] is True
    matrix = client.get(
        f"/api/traitbank/matrix?taxon_id={ANGRAECUM}", headers=headers
    ).json()
    assert matrix["graph_mutation"] is False
    assert (
        client.get(
            "/api/traitbank/characters/oc:trait:spur_length", headers=headers
        ).json()["state"]
        == "AVAILABLE"
    )
    assert (
        client.get("/api/traitbank/habitats?term=cloud forest", headers=headers).json()[
            "state"
        ]
        == "ABSENT"
    )


def test_routes_reject_fixture_ids_and_have_no_write_methods(client):
    headers = {"X-API-Key": API_KEY}
    assert (
        client.get("/api/traitbank/taxa/taxon:1002", headers=headers).status_code == 422
    )
    assert (
        client.get("/api/traitbank/characters/spur_length", headers=headers).status_code
        == 422
    )
    assert (
        client.post(f"/api/traitbank/taxa/{ANGRAECUM}", headers=headers).status_code
        == 405
    )
    for route in routes.router.routes:
        assert route.methods == {"GET"}, route.path
