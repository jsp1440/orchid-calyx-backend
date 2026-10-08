from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.calyx_orchestrator.program_routes import router
from app.database import get_db
from app.security import verify_owner_or_api_key


def client(auth):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[verify_owner_or_api_key] = auth
    def forbidden_db():
        raise AssertionError("Capability discovery must not open a database")
    app.dependency_overrides[get_db] = forbidden_db
    return TestClient(app)


def test_authenticated_discovery_is_read_only_and_precedes_dynamic_program_route():
    with client(lambda: {"subject": "fixture-owner"}) as http:
        first = http.get("/programs/submission-capabilities")
        second = http.get("/programs/submission-capabilities")
        assert first.status_code == second.status_code == 200
        assert first.json() == second.json() == {"capabilities": [
            "brain.verification_admission.v1", "programs.idempotency.v1",
        ]}


def test_authentication_is_not_bypassed():
    def denied():
        raise HTTPException(401, detail="fixture-denied")
    with client(denied) as http:
        assert http.get("/programs/submission-capabilities").status_code == 401
    with client(lambda: {}) as http:
        assert http.get("/programs/submission-capabilities").status_code == 401
