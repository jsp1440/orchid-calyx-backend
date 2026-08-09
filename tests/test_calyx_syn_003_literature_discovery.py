from fastapi.testclient import TestClient

from app.main import app
from app.scientific_synthesis.discovery import (
    BibliographicVerificationService,
    LiteratureDiscoveryService,
)
from app.scientific_synthesis import routes as synthesis_routes


class FakeProvider:
    name = "crossref"

    def __init__(self, *, lookup=None, items=None):
        self.lookup = lookup
        self.items = items or []
        self.search_calls = []
        self.lookup_calls = []

    def search(self, query: str, *, rows: int):
        self.search_calls.append((query, rows))
        return list(self.items)

    def lookup_doi(self, doi: str):
        self.lookup_calls.append(doi)
        return self.lookup


def _item(doi="10.1000/orchid.1", title="Orchid foliar nitrogen uptake"):
    return {
        "DOI": doi,
        "title": [title],
        "author": [
            {"given": "Ada", "family": "Researcher"},
            {"given": "Lin", "family": "Botanist"},
        ],
        "container-title": ["Journal of Orchid Science"],
        "published": {"date-parts": [[2026, 1, 2]]},
    }


def test_discovery_results_are_candidates_not_verified_evidence():
    provider = FakeProvider(items=[_item(), _item()])
    result = LiteratureDiscoveryService((provider,)).discover(
        "orchid foliar feeding", rows_per_provider=10
    )

    assert result["candidate_count"] == 1
    assert result["search_results_are_evidence"] is False
    assert result["search_results_are_verified"] is False
    assert result["candidates"][0]["state"] == "DISCOVERY_CANDIDATE"
    assert result["candidates"][0]["doi"] == "10.1000/orchid.1"


def test_doi_lookup_creates_provider_attributed_verified_record():
    provider = FakeProvider(lookup=_item())
    result = BibliographicVerificationService(provider).verify_doi(
        "https://doi.org/10.1000/ORCHID.1"
    )

    assert result["verified"] is True
    assert result["state"] == "BIBLIOGRAPHY_VERIFIED"
    assert result["record"]["source_id"] == "doi:10.1000/orchid.1"
    assert result["record"]["verification_state"].value == "VERIFIED_AUTHORITY"
    assert result["record"]["verification_provider"] == "crossref"
    assert result["record"]["verification_identifier"] == "10.1000/orchid.1"
    assert provider.lookup_calls == ["10.1000/orchid.1"]


def test_doi_identity_mismatch_is_not_verified():
    provider = FakeProvider(lookup=_item(doi="10.9999/different"))
    result = BibliographicVerificationService(provider).verify_doi(
        "10.1000/orchid.1"
    )

    assert result["verified"] is False
    assert result["reason"] == "DOI_IDENTITY_MISMATCH"


def test_incomplete_authoritative_metadata_is_not_verified():
    incomplete = _item()
    incomplete["author"] = []
    result = BibliographicVerificationService(FakeProvider(lookup=incomplete)).verify_doi(
        "10.1000/orchid.1"
    )

    assert result["verified"] is False
    assert result["reason"] == "INCOMPLETE_AUTHORITATIVE_METADATA"


def test_unresolved_doi_remains_unverified():
    result = BibliographicVerificationService(FakeProvider()).verify_doi(
        "10.1000/missing"
    )

    assert result == {
        "verified": False,
        "state": "BIBLIOGRAPHY_UNRESOLVED",
        "doi": "10.1000/missing",
        "provider": "crossref",
        "reason": "DOI_NOT_FOUND",
    }


def test_discovery_api_is_authenticated_and_uses_configured_service(monkeypatch):
    provider = FakeProvider(items=[_item()])
    monkeypatch.setattr(
        synthesis_routes, "DISCOVERY", LiteratureDiscoveryService((provider,))
    )
    monkeypatch.setenv("CALYX_API_KEY", "test-key")

    with TestClient(app) as client:
        path = "/api/scientific-interpretation/synthesis/discovery/search"
        assert client.post(path, json={"question": "foliar feeding"}).status_code == 401
        response = client.post(
            path,
            json={"question": "foliar feeding"},
            headers={"X-API-Key": "test-key"},
        )

    assert response.status_code == 200
    assert response.json()["candidate_count"] == 1
    assert response.json()["search_results_are_verified"] is False


def test_verify_doi_api_returns_authoritative_record(monkeypatch):
    provider = FakeProvider(lookup=_item())
    monkeypatch.setattr(
        synthesis_routes,
        "VERIFICATION",
        BibliographicVerificationService(provider),
    )
    monkeypatch.setenv("CALYX_API_KEY", "test-key")

    with TestClient(app) as client:
        response = client.post(
            "/api/scientific-interpretation/synthesis/discovery/verify-doi",
            json={"doi": "10.1000/orchid.1"},
            headers={"X-API-Key": "test-key"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["verified"] is True
    assert payload["record"]["verification_provider"] == "crossref"
