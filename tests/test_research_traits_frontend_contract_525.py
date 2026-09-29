"""GET /api/research/traits emits exactly what the frontend Trait Explorer reads.

The consumer contract is orchid-continuum-frontend ``src/lib/researchTraits.ts``
(zod, read-only for #525) and the reads in
``src/components/research/ResearchTraitExplorer.tsx``. Every rule below cites
the frontend line it ports:

* ``traitEvidenceState`` enum — researchTraits.ts:6-9
* ``text`` (trim, 1..512) — :11; ``count`` (int, >= 0, <= MAX_SAFE_INTEGER,
  nullable) — :12; ``optionalText`` — :13; ``sourceUrl`` (http/https, no
  credentials, nullable) — :14-17
* ``subjectSchema`` rank/name shape — :19-25
* ``receiptSchema`` keys — :27-34
* ``distributionSchema`` keys, ``confidence`` 0..1 nullable, ``buckets`` <= 200,
  ``receipts`` <= 100 — :36-47
* ``responseSchema``: ``contract_version`` literal, ``distributions`` <= 100 — :50-55;
  withheld response carries no distributions — :57-58; unique ``trait_id`` — :59-62;
  withheld distribution carries no buckets/receipts — :64-65; VERIFIED requires a
  receipt with ``source_id`` and ``record_id`` — :67-68
* Consumer reads — ResearchTraitExplorer.tsx:20-52 (label, evidence_state, unit,
  sample_size, confidence, buckets[].value/count, receipts[].source_name/
  source_id/record_id/retrieved_at/license/source_url), :126-133 (subject.name,
  subject.rank, state, generated_at, distributions, ABSENT wording).

The route is exercised through FastAPI's TestClient with the real
``ResearchTraitsService.get()`` pipeline over a fake connection, so what is
checked is the JSON the backend actually returns, not a hand-built dict.
Nothing here touches a database or the network.
"""

from __future__ import annotations

import math
import re
from typing import Any
from urllib.parse import urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.member_auth import owner_or_member_read
from app.research_traits import routes
from app.research_traits.service import ResearchTraitsService
from app.security import verify_owner_or_api_key

EVIDENCE_STATES = {
    "AVAILABLE",
    "PROVISIONAL",
    "VERIFIED",
    "CONTRADICTORY",
    "UNKNOWN",
    "UNAVAILABLE",
    "WITHHELD",
    "ABSENT",
    "REJECTED",
    "SUPERSEDED",
}  # researchTraits.ts:6-9
WITHHELD_STATES = {"UNAVAILABLE", "UNKNOWN", "WITHHELD", "ABSENT"}  # :49
MAX_SAFE_INTEGER = 2**53 - 1  # :12
RECEIPT_KEYS = {
    "source_id",
    "source_name",
    "source_url",
    "record_id",
    "retrieved_at",
    "license",
}
DISTRIBUTION_KEYS = {
    "trait_id",
    "label",
    "unit",
    "evidence_state",
    "confidence",
    "sample_size",
    "buckets",
    "receipts",
}
RESPONSE_KEYS = {
    "contract_version",
    "subject",
    "state",
    "generated_at",
    "distributions",
}
GENUS_RE = re.compile(r"^[A-Z][a-z-]+$")  # :22
SPECIES_RE = re.compile(r"^[A-Z][a-z-]+ [a-z][a-z-]+$")  # :23
LOCALITY_KEY = re.compile(
    r"lat|lon|long|coord|locality|geometry|elevation|point|wkt|geo", re.IGNORECASE
)


# -- a Python port of the zod contract ------------------------------------------


def _text(value: Any, where: str) -> None:
    assert isinstance(value, str), f"{where}: text must be a string"
    assert 1 <= len(value.strip()) <= 512, (
        f"{where}: text must be 1..512 chars after trim"
    )


def _optional_text(value: Any, where: str) -> None:
    if value is not None:
        _text(value, where)


def _count(value: Any, where: str) -> None:
    if value is None:
        return
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{where}: count must be int"
    )
    assert 0 <= value <= MAX_SAFE_INTEGER, f"{where}: count out of range"


def _source_url(value: Any, where: str) -> None:
    if value is None:
        return
    assert isinstance(value, str)
    parts = urlsplit(value)
    assert parts.scheme in {"http", "https"}, f"{where}: scheme"
    assert parts.username is None and parts.password is None, f"{where}: credentials"


def assert_frontend_contract(body: dict[str, Any]) -> None:
    assert set(body) == RESPONSE_KEYS, f"response keys {sorted(body)}"
    assert body["contract_version"] == "oc-research-traits-v1"  # :50
    subject = body["subject"]
    assert set(subject) == {"rank", "name"} and subject["rank"] in {"genus", "species"}
    _text(subject["name"], "subject.name")
    pattern = GENUS_RE if subject["rank"] == "genus" else SPECIES_RE
    assert pattern.fullmatch(subject["name"]), "subject.name does not match its rank"
    assert body["state"] in EVIDENCE_STATES
    _optional_text(body["generated_at"], "generated_at")
    distributions = body["distributions"]
    assert isinstance(distributions, list) and len(distributions) <= 100
    if body["state"] in WITHHELD_STATES:
        assert distributions == [], (
            "unavailable results must not contain trait records"
        )  # :57
    ids = [item["trait_id"] for item in distributions]
    assert len(set(ids)) == len(ids), "duplicate trait identity"  # :59-62
    for item in distributions:
        assert set(item) == DISTRIBUTION_KEYS, f"distribution keys {sorted(item)}"
        _text(item["trait_id"], "trait_id")
        _text(item["label"], "label")
        _optional_text(item["unit"], "unit")
        assert item["evidence_state"] in EVIDENCE_STATES
        confidence = item["confidence"]
        if confidence is not None:
            assert isinstance(confidence, (int, float)) and not isinstance(
                confidence, bool
            )
            assert math.isfinite(confidence) and 0 <= confidence <= 1
        _count(item["sample_size"], "sample_size")
        assert isinstance(item["buckets"], list) and len(item["buckets"]) <= 200
        for bucket in item["buckets"]:
            assert set(bucket) == {"value", "count"}
            value = bucket["value"]
            if isinstance(value, str):
                _text(value, "bucket.value")
            elif isinstance(value, bool):
                pytest.fail("bucket.value may not be a boolean")
            elif isinstance(value, (int, float)):
                assert math.isfinite(value)
            else:
                assert value is None
            _count(bucket["count"], "bucket.count")
        assert isinstance(item["receipts"], list) and len(item["receipts"]) <= 100
        for receipt in item["receipts"]:
            assert set(receipt) == RECEIPT_KEYS, f"receipt keys {sorted(receipt)}"
            for key in RECEIPT_KEYS - {"source_url"}:
                _optional_text(receipt[key], f"receipt.{key}")
            _source_url(receipt["source_url"], "receipt.source_url")
        if item["evidence_state"] in WITHHELD_STATES:  # :64-65
            assert item["buckets"] == [] and item["receipts"] == []
        if item["evidence_state"] == "VERIFIED":  # :67-68
            assert any(r["source_id"] and r["record_id"] for r in item["receipts"])


def assert_no_locality(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, inner in value.items():
            assert not LOCALITY_KEY.search(str(key)), (
                f"locality-shaped key at {path}.{key}"
            )
            assert_no_locality(inner, f"{path}.{key}")
    elif isinstance(value, list):
        for index, inner in enumerate(value):
            assert_no_locality(inner, f"{path}[{index}]")


# -- the route over the real pipeline with a fake connection ---------------------


class _Cursor:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _Connection:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return _Cursor()


class FakeService(ResearchTraitsService):
    """The real get() pipeline; only the database boundary is replaced."""

    def __init__(
        self,
        *,
        taxon_ids: list[str],
        rows: list[dict[str, Any]] | None,
        source_table: str | None = "oc_views.trait_resolved_v4",
        connection_error: bool = False,
    ) -> None:
        super().__init__(
            database_url="fixture-only", connection_factory=lambda _: _Connection()
        )
        self.taxon_ids = taxon_ids
        self.rows = rows
        self.source_table = source_table
        self.connection_error = connection_error

    def _connect(self):
        if self.connection_error:
            raise RuntimeError("DATABASE_URL is required for research trait retrieval")
        return _Connection()

    def _resolve_taxon_ids(self, cur, *, rank, name):
        return list(self.taxon_ids)

    def _read_trait_rows(self, cur, taxon_ids):
        return self.source_table, list(self.rows or [])


def client_for(
    service: ResearchTraitsService, monkeypatch: pytest.MonkeyPatch
) -> TestClient:
    monkeypatch.setattr(routes, "get_service", lambda: service)
    app = FastAPI()
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {
        "subject": "test-owner"
    }
    app.dependency_overrides[owner_or_member_read] = lambda: {"subject": "test-owner"}
    app.include_router(routes.router)
    return TestClient(app)


ROWS = [
    {
        "trait_id": "growth-form",
        "trait_name": "growth form",
        "trait_value": "epiphyte",
        "evidence_state": "VERIFIED",
        "support_count": 4,
        "confidence_score": 0.9,
        "source_id": "eol-traitbank",
        "source_name": "EOL TraitBank",
        "record_id": "r-1",
        "source_url": "https://example.org/records/r-1",
        "retrieved_at": "2026-09-01",
        "license": "CC-BY-4.0",
    },
    {
        "trait_id": "growth-form",
        "trait_name": "growth form",
        "trait_value": "terrestrial",
        "evidence_state": "VERIFIED",
        "support_count": None,
        "confidence_score": 0.7,
        "source_id": "eol-traitbank",
        "source_name": "EOL TraitBank",
        "record_id": "r-2",
        "source_url": "https://user:secret@example.org/r-2",
        "retrieved_at": "",
        "license": None,
    },
    {
        "trait_id": "flower-width",
        "trait_name": "flower width",
        "unit": "mm",
        "trait_value": 42,
        "evidence_state": "AVAILABLE",
        "count": 3,
        "sample_size": 3,
        "record_id": "r-3",
    },
    {
        "trait_id": "scent-class",
        "trait_name": "scent class",
        "trait_value": "floral",
        "evidence_state": "AVAILABLE",
        "support_count": 3,
        "source_id": "public",
        "record_id": "p-1",
    },
    {
        "trait_id": "scent-class",
        "trait_name": "scent class",
        "trait_value": "restricted",
        "evidence_state": "WITHHELD",
        "support_count": 10,
        "source_id": "restricted",
        "record_id": "private-1",
        "decimal_latitude": -12.5,
        "decimal_longitude": -70.1,
    },
]


def test_available_response_satisfies_every_frontend_rule(monkeypatch):
    client = client_for(FakeService(taxon_ids=["t-1"], rows=ROWS), monkeypatch)
    response = client.get(
        "/api/research/traits", params={"species": "Cattleya purpurata"}
    )
    assert response.status_code == 200
    body = response.json()
    assert_frontend_contract(body)
    assert_no_locality(body)
    assert body["subject"] == {"rank": "species", "name": "Cattleya purpurata"}
    assert body["state"] == "AVAILABLE"
    assert body["generated_at"]
    by_id = {item["trait_id"]: item for item in body["distributions"]}
    assert set(by_id) == {"growth-form", "flower-width", "scent-class"}

    growth = by_id["growth-form"]
    assert growth["evidence_state"] == "VERIFIED"
    # An unknown count never renders as zero (ResearchTraitExplorer.tsx:35 shows UNKNOWN).
    assert growth["buckets"] == [
        {"value": "epiphyte", "count": 4},
        {"value": "terrestrial", "count": None},
    ]
    assert growth["sample_size"] is None
    assert growth["confidence"] == 0.7
    receipts = {r["record_id"]: r for r in growth["receipts"]}
    assert receipts["r-1"]["source_url"] == "https://example.org/records/r-1"
    assert (
        receipts["r-2"]["source_url"] is None
    )  # credentials in URL are never returned
    assert receipts["r-2"]["retrieved_at"] is None  # "" is not a text value (:11, :13)

    width = by_id["flower-width"]
    assert width["unit"] == "mm" and width["sample_size"] == 3
    assert width["buckets"] == [{"value": 42, "count": 3}]

    # A group with one WITHHELD member discloses nothing of the group (#1405 semantics).
    scent = by_id["scent-class"]
    assert scent["evidence_state"] == "WITHHELD"
    assert scent["buckets"] == [] and scent["receipts"] == []
    assert scent["sample_size"] is None and scent["confidence"] is None


@pytest.mark.parametrize(
    ("service", "expected_state", "generated"),
    [
        (FakeService(taxon_ids=[], rows=None), "UNKNOWN", False),
        (
            FakeService(taxon_ids=["t-1"], rows=None, connection_error=True),
            "UNAVAILABLE",
            False,
        ),
        (
            FakeService(taxon_ids=["t-1"], rows=[], source_table=None),
            "UNAVAILABLE",
            False,
        ),
        (FakeService(taxon_ids=["t-1"], rows=[]), "ABSENT", True),
        (
            FakeService(
                taxon_ids=["t-1"], rows=[{"trait_name": "x", "trait_value": None}]
            ),
            "UNKNOWN",
            True,
        ),
    ],
)
def test_every_withheld_state_the_frontend_renders_is_produced(
    monkeypatch, service, expected_state, generated
):
    client = client_for(service, monkeypatch)
    body = client.get("/api/research/traits", params={"genus": "Cattleya"}).json()
    assert_frontend_contract(body)
    assert body["state"] == expected_state
    assert body["distributions"] == []
    assert (body["generated_at"] is not None) is generated
    assert body["subject"] == {"rank": "genus", "name": "Cattleya"}


@pytest.mark.parametrize(
    "state",
    [
        "AVAILABLE",
        "PROVISIONAL",
        "VERIFIED",
        "CONTRADICTORY",
        "UNKNOWN",
        "UNAVAILABLE",
        "WITHHELD",
        "ABSENT",
        "REJECTED",
        "SUPERSEDED",
    ],
)
def test_every_evidence_state_in_the_frontend_enum_passes_through(monkeypatch, state):
    rows = [
        {
            "trait_name": "growth form",
            "trait_value": "epiphyte",
            "evidence_state": state,
            "support_count": 1,
            "source_id": "s",
            "record_id": "r",
        }
    ]
    if state == "CONTRADICTORY":
        rows.append(
            {
                "trait_name": "growth form",
                "trait_value": "terrestrial",
                "evidence_state": "AVAILABLE",
                "support_count": 1,
            }
        )
    client = client_for(FakeService(taxon_ids=["t-1"], rows=rows), monkeypatch)
    body = client.get("/api/research/traits", params={"genus": "Cattleya"}).json()
    assert_frontend_contract(body)
    assert body["distributions"][0]["evidence_state"] == state


def test_subject_is_echoed_exactly_so_the_client_identity_check_holds(monkeypatch):
    """researchTraits.ts:95-97 rejects a response whose subject differs from the request."""
    client = client_for(FakeService(taxon_ids=["t-1"], rows=[]), monkeypatch)
    body = client.get(
        "/api/research/traits", params={"species": "Cattleya purpurata"}
    ).json()
    assert body["subject"] == {"rank": "species", "name": "Cattleya purpurata"}


def test_route_requires_authentication_like_the_rest_of_the_research_api():
    app = FastAPI()
    app.include_router(routes.router)
    response = TestClient(app).get("/api/research/traits", params={"genus": "Cattleya"})
    assert response.status_code in {
        401,
        403,
    }  # researchStation.ts:92 -> authentication_required


def test_two_groups_sharing_a_label_never_share_a_trait_identity(monkeypatch):
    """researchTraits.ts:59-62 rejects the whole response on a duplicate trait_id."""
    rows = [
        {
            "trait_name": "flower width",
            "unit": "mm",
            "trait_value": None,
            "evidence_state": "WITHHELD",
        },
        {
            "trait_name": "flower width",
            "unit": "cm",
            "trait_value": None,
            "evidence_state": "WITHHELD",
        },
        {
            "trait_name": "flower width",
            "trait_value": 42,
            "evidence_state": "AVAILABLE",
            "count": 1,
        },
    ]
    client = client_for(FakeService(taxon_ids=["t-1"], rows=rows), monkeypatch)
    body = client.get("/api/research/traits", params={"genus": "Cattleya"}).json()
    assert_frontend_contract(body)
    ids = sorted(item["trait_id"] for item in body["distributions"])
    assert len(set(ids)) == 3
    # Groups are visited in label order, first-come keeps the bare identity; a
    # later collision takes its unit, and a unit-less collision takes an ordinal.
    assert ids == ["flower width", "flower width #2", "flower width [cm]"]
