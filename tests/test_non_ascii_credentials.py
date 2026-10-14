"""A non-ASCII credential is a wrong credential (401), never a 500.

``hmac.compare_digest`` raises ``TypeError`` for a ``str`` containing any
non-ASCII character. Starlette decodes headers as latin-1 and query values as
UTF-8, so an ``X-API-Key`` such as ``b"k\\xe9"`` or an emoji, or a manage token
``?token=%C3%A9``, used to crash the auth dependency with a 500.
``app.security.credentials_match`` compares the UTF-8 bytes instead, keeping the
constant-time comparison.
"""

from __future__ import annotations

import ast
import hashlib
import hmac
import re
from pathlib import Path

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

from app.constituent_platform import service as constituent_service
from app.constituent_platform.routes import router as constituent_router
from app.main import app as real_app
from app.member_auth import member_readable, owner_or_member_read, owner_session_only
from app.routers.github_research_bridge import router as github_bridge_router
from app.routers.health import add_mission_control_cors_headers
from app.security import (
    OWNER_SESSION_COOKIE,
    create_owner_session_token,
    credentials_match,
    require_admin,
    verify_api_key,
    verify_owner_or_api_key,
)

API_KEY = "non-ascii-test-key"
ADMIN_KEY = "non-ascii-admin-key"
REPO = Path(__file__).resolve().parents[1]

# Raw header bytes as a client puts them on the wire.
NON_ASCII_VALUES = {
    "latin-1": b"k\xe9y",
    "emoji-utf8": "\U0001f33a".encode(),
    "valid-key-plus-latin-1": API_KEY.encode() + b"\xff",
    "valid-key-plus-emoji": (API_KEY + "\U0001f33a").encode(),
    "cyrillic-lookalike": "non-аscii-test-key".encode(),
}


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setenv("CALYX_API_KEY", API_KEY)
    monkeypatch.setenv("CALYX_OWNER_SESSION_SECRET", "s" * 32)
    monkeypatch.setenv("ORCHID_JUDGE_ADMIN_KEY", ADMIN_KEY)
    for name in ("OC_SUPABASE_URL", "OCU_SUPABASE_URL", "OC_SUPABASE_ANON_KEY", "OCU_SUPABASE_ANON_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("OC_MEMBER_READS_ENABLED", raising=False)


@pytest.fixture
def mini() -> TestClient:
    """The real auth dependencies, each on an endpoint that needs no database."""
    app = FastAPI()

    @app.get("/api-key", dependencies=[Depends(verify_api_key)])
    def api_key_only():
        return {"ok": True}

    @app.get("/owner-or-key", dependencies=[Depends(verify_owner_or_api_key)])
    def owner_or_key():
        return {"ok": True}

    @app.get("/admin", dependencies=[Depends(require_admin)])
    def admin():
        return {"ok": True}

    gated = APIRouter(dependencies=[Depends(owner_or_member_read)])

    @gated.get("/owner-or-member")
    def owner_or_member():
        return {"ok": True}

    @gated.get("/member-read")
    @member_readable
    def member_read():
        return {"ok": True}

    app.include_router(gated)

    @app.get("/owner-session-only", dependencies=[Depends(owner_session_only)])
    def owner_session():
        return {"ok": True}

    return TestClient(app, raise_server_exceptions=False)


KEY_ROUTES = {
    # route: status for the valid key
    "/api-key": 200,
    "/owner-or-key": 200,
    "/owner-or-member": 200,
    "/member-read": 200,
    "/owner-session-only": 403,  # the API key is not the owner
}


@pytest.mark.parametrize("route", sorted(KEY_ROUTES))
@pytest.mark.parametrize("value", sorted(NON_ASCII_VALUES))
def test_non_ascii_api_key_is_answered_exactly_like_a_wrong_key(mini, route, value):
    wrong = mini.get(route, headers={"X-API-Key": "wrong-key"})
    non_ascii = mini.get(route, headers={"X-API-Key": NON_ASCII_VALUES[value]})
    assert wrong.status_code == 401
    assert (non_ascii.status_code, non_ascii.content) == (wrong.status_code, wrong.content)


@pytest.mark.parametrize("route", sorted(KEY_ROUTES))
def test_valid_and_missing_api_key_are_unchanged(mini, route):
    assert mini.get(route, headers={"X-API-Key": API_KEY}).status_code == KEY_ROUTES[route]
    assert mini.get(route).status_code == 401


@pytest.mark.parametrize("value", sorted(NON_ASCII_VALUES))
def test_non_ascii_admin_key_is_401(mini, value):
    assert mini.get("/admin", headers={"X-Orchid-Admin-Key": NON_ASCII_VALUES[value]}).status_code == 401
    assert mini.get("/admin", headers={"X-Orchid-Admin-Key": ADMIN_KEY}).status_code == 200


def _owner_token() -> str:
    return str(create_owner_session_token("owner")["token"])


def _with_non_ascii_signature(token: str, tail: bytes) -> bytes:
    payload, _, _signature = token.partition(".")
    return payload.encode() + b"." + tail


@pytest.mark.parametrize("route", ["/owner-or-key", "/owner-or-member", "/owner-session-only"])
@pytest.mark.parametrize("carrier", ["cookie", "bearer"])
def test_non_ascii_owner_session_token_is_401_like_an_invalid_token(mini, route, carrier):
    def send(token: bytes):
        if carrier == "cookie":
            return mini.get(route, headers={"cookie": OWNER_SESSION_COOKIE.encode() + b"=" + token})
        return mini.get(route, headers={"authorization": b"Bearer " + token})

    invalid = send(b"not-a-token")
    assert invalid.status_code == 401
    for token in (
        b"\xe9\xff",
        "\U0001f33a".encode(),
        _with_non_ascii_signature(_owner_token(), b"\xe9" * 64),
        _with_non_ascii_signature(_owner_token(), "\U0001f33a".encode() * 16),
    ):
        response = send(token)
        assert (response.status_code, response.content) == (invalid.status_code, invalid.content), token
    assert send(_owner_token().encode()).status_code == 200


def test_real_app_owner_review_route_refuses_non_ascii_key_with_401():
    client = TestClient(real_app, raise_server_exceptions=False)
    route = "/api/evidence-feedback/review/cases"
    wrong = client.get(route, headers={"X-API-Key": "wrong-key"})
    assert wrong.status_code == 401
    for value in NON_ASCII_VALUES.values():
        response = client.get(route, headers={"X-API-Key": value})
        assert (response.status_code, response.content) == (401, wrong.content)
        cookie = client.get(route, headers={"cookie": OWNER_SESSION_COOKIE.encode() + b"=" + value})
        assert cookie.status_code == 401
    assert client.get(route, headers={"X-API-Key": API_KEY}).status_code == 403


@pytest.fixture
def constituent(monkeypatch) -> TestClient:
    monkeypatch.setenv("CONSTITUENT_MANAGE_SECRET", "test-secret")
    monkeypatch.delenv("PUBLIC_WRITE_RATE_LIMIT", raising=False)
    constituent_service.configure_store(constituent_service.memory_store())
    app = FastAPI()
    app.include_router(constituent_router)
    app.dependency_overrides[add_mission_control_cors_headers] = lambda: None
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        constituent_service.configure_store(None)


def test_non_ascii_manage_token_is_401_and_the_real_token_still_works(constituent):
    email = "user@example.com"
    token = constituent.post("/api/constituent/subscribe", json={"email": email}).json()["manage_token"]
    assert token
    url = "/api/constituent/preferences"
    for bad in ("é", "\U0001f33a", token[:-1] + "é", token + "\U0001f33a"):
        assert constituent.get(url, params={"email": email, "token": bad}).status_code == 401, bad
    assert constituent.get(f"{url}?email={email}&token=%FF%FE").status_code == 401
    assert constituent.get(url, params={"email": email, "token": token}).status_code == 200


def test_non_ascii_github_webhook_signature_is_401(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("CALYX_GITHUB_RESEARCH_BRIDGE_ENABLED", "true")
    monkeypatch.setenv("CALYX_GITHUB_RESEARCH_WEBHOOK_SECRET", "bridge-test-secret")
    monkeypatch.setenv("CALYX_GITHUB_RESEARCH_REPOSITORIES", "jsp1440/Orchid-Continuum-Brain")
    monkeypatch.setenv("CALYX_GITHUB_RESEARCH_AUTHORS", "jsp1440")
    monkeypatch.setenv("CALYX_GITHUB_RESEARCH_LABEL", "calyx-research")
    app = FastAPI()
    app.include_router(github_bridge_router)
    client = TestClient(app, raise_server_exceptions=False)
    raw = b'{"action":"labeled"}'
    good = "sha256=" + hmac.new(b"bridge-test-secret", raw, hashlib.sha256).hexdigest()
    for signature in (b"sha256=\xe9", ("sha256=" + "\U0001f33a").encode(), good[:-1].encode() + b"\xe9"):
        response = client.post(
            "/api/integrations/github/research/issues",
            content=raw,
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": "issues",
                "X-GitHub-Delivery": "delivery-non-ascii",
                "X-Hub-Signature-256": signature,
            },
        )
        assert response.status_code == 401, response.text
        assert response.json()["detail"]["code"] == "GITHUB_RESEARCH_SIGNATURE_INVALID"


# --- the comparison itself --------------------------------------------------------


def test_credentials_match_semantics():
    assert credentials_match("abc", "abc")
    assert not credentials_match("abd", "abc")
    assert not credentials_match("", "abc")
    assert not credentials_match("abcé", "abc")
    assert not credentials_match("\U0001f33a", "abc")
    assert credentials_match("café", "café")
    assert not credentials_match("\ud800", "abc")  # never raises, even for a lone surrogate


def test_every_credential_check_stays_constant_time(mini, monkeypatch):
    calls: list[tuple[object, object]] = []
    real = hmac.compare_digest

    def spy(a, b):
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(hmac, "compare_digest", spy)
    for route in KEY_ROUTES:
        mini.get(route, headers={"X-API-Key": NON_ASCII_VALUES["latin-1"]})
    mini.get("/owner-or-key", headers={"cookie": f"{OWNER_SESSION_COOKIE}={_owner_token()}"})
    assert len(calls) >= len(KEY_ROUTES) + 1
    assert all(isinstance(a, bytes) and isinstance(b, bytes) for a, b in calls)


AUTH_MODULES = [
    "app/security.py",
    "app/member_auth.py",
    "app/constituent_platform/service.py",
    "app/routers/github_research_bridge.py",
    "app/routers/reference_docs.py",
    "app/review_api/dependencies.py",
    "app/calyx_orchestrator/sandbox_supervisor_service.py",
]

# Worker lease tokens are bearer secrets too (#1671/#1673 follow-up). Each module maps
# to the ORM models whose column comparisons it may use in a SQL filter: for example
# ``CalyxJob.lease_token == lease_token`` inside ``.filter()`` is evaluated by the
# database, not by a Python short-circuit, so only those column expressions are exempt.
LEASE_MODULES = {
    "app/calyx_engineering/completion_scheduler.py": frozenset({"CalyxJob"}),
    "app/calyx_orchestrator/dry_run_service.py": frozenset(),
    "app/calyx_orchestrator/execution_bridge.py": frozenset(),
}

# Identifiers that name a presented or expected secret. A ``==``/``!=`` between
# two such runtime values short-circuits on the first differing byte (a timing
# oracle) and must go through app.security.credentials_match instead.
SECRET_NAME = re.compile(r"(api_key|admin_key|effective_key|secret|token|signature|password|access_code|^expected$)", re.IGNORECASE)


def _operand_names(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, ast.Attribute):
        return {node.attr}
    if isinstance(node, ast.Call):
        return _operand_names(node.func)
    return set()


def _is_sql_column(node: ast.AST, sql_models: frozenset[str]) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id in sql_models
    )


def _raw_secret_equality(tree: ast.AST, sql_models: frozenset[str] = frozenset()) -> list[int]:
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        operands = [node.left, *node.comparators]
        for op, left, right in zip(node.ops, operands, operands[1:]):
            if not isinstance(op, (ast.Eq, ast.NotEq)):
                continue
            if isinstance(left, ast.Constant) or isinstance(right, ast.Constant):
                continue  # e.g. ``scheme == "bearer"`` or ``token is None``-style checks
            if _is_sql_column(left, sql_models) or _is_sql_column(right, sql_models):
                continue  # a SQLAlchemy column expression, compared by the database
            names = _operand_names(left) | _operand_names(right)
            if any(SECRET_NAME.search(name) for name in names):
                found.append(node.lineno)
    return found


@pytest.mark.parametrize("module", AUTH_MODULES + list(LEASE_MODULES))
def test_request_credentials_are_never_compared_as_raw_strings(module):
    """Every compare_digest in the auth modules compares bytes: via credentials_match or .encode()."""
    tree = ast.parse((REPO / module).read_text(encoding="utf-8"))
    helper = next(
        (node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "credentials_match"),
        None,
    )
    inside_helper = {id(node) for node in ast.walk(helper)} if helper else set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "compare_digest"):
            continue
        if id(node) in inside_helper:
            continue
        for arg in node.args:
            assert (
                isinstance(arg, ast.Call) and getattr(arg.func, "attr", None) == "encode"
            ), f"{module}:{node.lineno} compares a str; use app.security.credentials_match"


@pytest.mark.parametrize("module", AUTH_MODULES + list(LEASE_MODULES))
def test_request_credentials_are_never_compared_with_equality_operators(module):
    """No ``==``/``!=`` between secret-named values in the auth modules: use credentials_match."""
    tree = ast.parse((REPO / module).read_text(encoding="utf-8"))
    lines = _raw_secret_equality(tree, LEASE_MODULES.get(module, frozenset()))
    assert not lines, f"{module}: raw secret equality at line(s) {lines}; use app.security.credentials_match"


@pytest.mark.parametrize(
    "source",
    [
        "if api_key != effective_key: pass",
        "if not expected or api_key != expected: pass",
        "if record.claim_worker != worker_id or record.claim_token != claim_token: pass",
        "ok = signature == hmac_signature(x)",
        "if job.lease_owner != worker_id or job.lease_token != lease_token: pass",
        "if job.status != 'running' or job.lease_token != lease_token: pass",
    ],
)
def test_equality_guard_detects_raw_secret_compares(source):
    """Negative control: the guard flags each pattern this hardening removed."""
    assert _raw_secret_equality(ast.parse(source))


@pytest.mark.parametrize(
    "source",
    [
        'if scheme.lower() == "bearer": pass',
        "if record.claim_worker != worker_id: pass",
        "if not credentials_match(api_key, expected): pass",
    ],
)
def test_equality_guard_ignores_non_secret_compares(source):
    assert not _raw_secret_equality(ast.parse(source))


def test_equality_guard_exempts_only_the_named_sql_models():
    """The SQL-column exemption covers ``Model.column`` of the listed models only."""
    sql_filter = ast.parse("q.filter(CalyxJob.lease_token == lease_token)")
    python_side = ast.parse("if job.lease_token != lease_token: pass")
    assert not _raw_secret_equality(sql_filter, frozenset({"CalyxJob"}))
    assert _raw_secret_equality(sql_filter)  # not exempt unless the model is listed
    assert _raw_secret_equality(python_side, frozenset({"CalyxJob"}))
    assert _raw_secret_equality(
        ast.parse("q.filter(OtherModel.lease_token == lease_token)"), frozenset({"CalyxJob"})
    )
