from pathlib import Path


ROOT = Path(__file__).parents[1]
CLIENT = ROOT / "client"


def test_build_092_frontend_artifacts_and_working_routes_exist():
    required = {
        "src/App.tsx",
        "src/api.ts",
        "src/components.tsx",
        "src/domain.ts",
        "src/pages.tsx",
        "src/routing.ts",
        "src/styles.css",
        "src/test/domain.test.ts",
        "src/test/pages.test.tsx",
        "src/test/components.test.tsx",
        "src/test/routing.test.ts",
        "pnpm-lock.yaml",
    }
    assert all((CLIENT / path).is_file() for path in required)
    pages = (CLIENT / "src/pages.tsx").read_text(encoding="utf-8")
    for page in (
        "Dashboard",
        "PlantsPage",
        "PlantDetail",
        "AddPlant",
        "SearchPage",
        "QRScanner",
    ):
        assert f"function {page}" in pages


def test_existing_backend_adapter_is_authenticated_and_nonduplicative():
    adapter = (CLIENT / "src/api.ts").read_text(encoding="utf-8")
    assert "/api/implementation-planning/health" in adapter
    assert "/judging/events/" in adapter
    assert "/judging/plants/" in adapter
    assert 'method: "POST"' in adapter
    assert "X-API-Key" in adapter and "Authorization" in adapter
    assert "missingBuild091Endpoints" in adapter
    assert "/api/conservatory/collections" in adapter


def test_privacy_scientific_provenance_and_deferred_contracts_are_explicit():
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (CLIENT / "src").glob("*.tsx")
    )
    domain = (CLIENT / "src/domain.ts").read_text(encoding="utf-8")
    assert "sessionStorage" in source and "localStorage" not in source
    assert "acceptedScientificName" in domain
    assert "uncertainIdentification" in domain
    assert "provenance" in domain
    assert "No placeholder data is shown" in source
    assert "Knowledge Graph" not in source
