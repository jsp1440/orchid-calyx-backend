"""Security: calyx_core show-management routes are owner-only and their output is safe.

Organizations, org shows, message templates (+ render), events (+ ICS export), files
and integrations in ``app/routers/calyx_core.py`` require the owner session or the
API key. A verified member gets 403 OWNER_ACCESS_REQUIRED; anonymous and invalid
credentials get 401 before any lookup or body validation, and anonymous writes store
nothing. Integration ``config_json`` secrets are masked in every response while the
stored value is kept. ICS text is RFC 5545 escaped and folded. Two routes that always
returned 500 (org show create, template render) work, and render is bounded. The
``/contacts`` routes are covered separately and are not asserted here. Supabase is
always mocked; all data is clearly synthetic.
"""

from __future__ import annotations

import base64
import json
import re
import time
from datetime import date, datetime, timezone
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import member_auth
from app.database import get_db
from app.main import app
from app.models import (
    Event,
    File,
    IntegrationConnection,
    MessageTemplate,
    Organization,
    Show,
)
from app.routers import calyx_core
from app.security import OWNER_SESSION_COOKIE, create_owner_session_token
from app.show_output_safety import (
    MAX_CONFIG_DEPTH,
    MAX_CONFIG_JSON_CHARS,
    MAX_REDACT_DEPTH,
    MAX_RENDERED_CHARS,
    MAX_TEMPLATE_CHARS,
    ics_escape_text,
    ics_fold,
    ics_strip_line_breaks,
    ics_utc_timestamp,
    json_nesting_depth,
    redact_config_json,
)

SUPABASE_GET = "app.university.learner_auth.requests.get"
MEMBER_UUID = "44444444-4444-4444-4444-444444444444"
API_KEY = "test-api-key"
OWNER_ACCESS_REQUIRED_BODY = {
    "detail": {
        "code": "OWNER_ACCESS_REQUIRED",
        "message": "This view is limited to owner access",
    }
}

ORG_ID = "org-core-1"
OTHER_ORG_ID = "org-core-2"
SHOW_ID = "show-core-1"
OTHER_SHOW_ID = "show-core-2"
TEMPLATE_ID = "tpl-core-1"
ORG_TEMPLATE_ID = "tpl-core-org"
OTHER_SHOW_TEMPLATE_ID = "tpl-core-other"
VOLUNTEER_TOKEN = "synthetic-volunteer-token-value"
STORAGE_KEY = "synthetic/storage/key/file-1.pdf"
UPLOADER = "synthetic.uploader@example.invalid"
SECRET_PASSWORD = "synthetic-password-value"
SECRET_API_KEY = "synthetic-api-key-value"
SECRET_BEARER = "Bearer synthetic-bearer-value"
SECRET_QUERY_TOKEN = "synthetic-query-token"
SECRET_URL_PASSWORD = "synthetic-url-password"
SECRETS = (
    SECRET_PASSWORD,
    SECRET_API_KEY,
    SECRET_BEARER,
    SECRET_QUERY_TOKEN,
    SECRET_URL_PASSWORD,
)
STORED_CONFIG = {
    "username": "synthetic-user",
    "password": SECRET_PASSWORD,
    "api_key": SECRET_API_KEY,
    "headers": {"Authorization": SECRET_BEARER, "Accept": "application/json"},
    "url": f"https://hooks.example.invalid/in?channel=show&token={SECRET_QUERY_TOKEN}",
    "smtp": [
        {
            "host": "smtp.example.invalid",
            "dsn": f"smtp://mailer:{SECRET_URL_PASSWORD}@smtp.example.invalid",
        }
    ],
    "enabled_events": ["entry.created"],
}
OWNER_ONLY_MARKERS = (VOLUNTEER_TOKEN, STORAGE_KEY, UPLOADER, *SECRETS)

# Every calyx_core show-management route: (method, path, body). /contacts excluded.
ROUTES = [
    ("GET", "/api/organizations", None),
    ("POST", "/api/organizations", {"name": "Synthetic New Society"}),
    ("GET", f"/api/organizations/{ORG_ID}/shows", None),
    (
        "POST",
        f"/api/organizations/{ORG_ID}/shows",
        {"name": "Synthetic Spring Show", "start_date": "2027-04-10"},
    ),
    ("GET", f"/api/shows/{SHOW_ID}/templates", None),
    (
        "POST",
        f"/api/shows/{SHOW_ID}/templates",
        {"name": "reminder", "body_template": "Hello {name}"},
    ),
    (
        "POST",
        f"/api/shows/{SHOW_ID}/templates/{TEMPLATE_ID}/render",
        {"context": {"name": "Ada", "place": "Hall B"}},
    ),
    ("GET", f"/api/shows/{SHOW_ID}/events", None),
    (
        "POST",
        f"/api/shows/{SHOW_ID}/events",
        {"title": "Setup", "starts_at": "2027-03-12T08:00:00"},
    ),
    ("GET", f"/api/shows/{SHOW_ID}/events/ics", None),
    ("GET", f"/api/shows/{SHOW_ID}/files", None),
    ("POST", f"/api/shows/{SHOW_ID}/files", {"filename": "schedule.pdf"}),
    ("GET", f"/api/shows/{SHOW_ID}/integrations", None),
    (
        "POST",
        f"/api/shows/{SHOW_ID}/integrations",
        {
            "provider": "webhook",
            "status": "enabled",
            "config_json": json.dumps({"url": "https://attacker.invalid"}),
        },
    ),
]
ROUTE_IDS = [f"{method} {path}" for method, path, _ in ROUTES]
WRITE_TABLES = (Organization, Show, MessageTemplate, Event, File, IntegrationConnection)


def _jwt(sub: str = MEMBER_UUID, marker: str = "a") -> str:
    def enc(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    return f"{enc({'alg': 'HS256', 'typ': 'JWT'})}.{enc({'sub': sub, 'exp': int(time.time() + 3600), 'm': marker})}.sig"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for name in (
        "OC_MEMBER_READS_ENABLED",
        "OCU_SUPABASE_URL",
        "OCU_SUPABASE_ANON_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CALYX_API_KEY", API_KEY)
    monkeypatch.setenv("CALYX_OWNER_SESSION_SECRET", "test-owner-secret")
    monkeypatch.setenv("OC_SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv("OC_SUPABASE_ANON_KEY", "anon-key")
    member_auth.clear_member_token_cache()
    yield
    member_auth.clear_member_token_cache()


@pytest.fixture
def session_local():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    for model in WRITE_TABLES:
        model.__table__.create(engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    with factory() as db:
        db.add(Organization(id=ORG_ID, name="Synthetic Orchid Society"))
        db.add(Organization(id=OTHER_ORG_ID, name="Other Synthetic Society"))
        db.add(
            Show(
                id=SHOW_ID,
                organization_id=ORG_ID,
                name="Synthetic Show",
                start_date=date(2027, 3, 13),
                public_volunteer_token=VOLUNTEER_TOKEN,
            )
        )
        db.add(
            Show(
                id=OTHER_SHOW_ID,
                organization_id=OTHER_ORG_ID,
                name="Other Show",
                start_date=date(2027, 5, 1),
            )
        )
        db.add(
            MessageTemplate(
                id=TEMPLATE_ID,
                show_id=SHOW_ID,
                name="welcome",
                subject_template="Welcome {name}",
                body_template="Dear {name}, see you at {{booth}} {place}.",
            )
        )
        db.add(
            MessageTemplate(
                id=ORG_TEMPLATE_ID,
                organization_id=ORG_ID,
                name="org",
                body_template="Org {name}",
            )
        )
        db.add(
            MessageTemplate(
                id=OTHER_SHOW_TEMPLATE_ID,
                show_id=OTHER_SHOW_ID,
                name="other",
                body_template="{name}",
            )
        )
        db.add(
            File(
                id="file-1",
                show_id=SHOW_ID,
                filename="plan.pdf",
                storage_key=STORAGE_KEY,
                uploaded_by=UPLOADER,
            )
        )
        db.add(
            IntegrationConnection(
                id="integ-1",
                show_id=SHOW_ID,
                provider="webhook",
                status="enabled",
                config_json=json.dumps(STORED_CONFIG),
            )
        )
        db.add(
            IntegrationConnection(
                id="integ-org",
                organization_id=ORG_ID,
                provider="legacy",
                config_json="opaque-legacy-" + SECRET_PASSWORD,
            )
        )
        db.commit()

    def override_get_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    yield factory
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def client(session_local) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def supabase(monkeypatch) -> Mock:
    response = Mock(status_code=200, ok=True)
    response.json.return_value = {"id": MEMBER_UUID, "email": "member@example.org"}
    mock = Mock(return_value=response)
    monkeypatch.setattr(SUPABASE_GET, mock)
    return mock


@pytest.fixture
def owner_token() -> str:
    return str(create_owner_session_token("owner")["token"])


def _owner_headers(
    client: TestClient, credential: str, owner_token: str
) -> dict[str, str]:
    if credential == "api_key":
        return {"X-API-Key": API_KEY}
    if credential == "owner_bearer":
        return {"Authorization": f"Bearer {owner_token}"}
    client.cookies.set(OWNER_SESSION_COOKIE, owner_token)
    return {}


def _counts(session_local) -> dict[str, int]:
    with session_local() as db:
        return {model.__name__: db.query(model).count() for model in WRITE_TABLES}


def _call(client: TestClient, method: str, path: str, body, headers=None):
    return client.request(method, path, json=body, headers=headers or {})


def _assert_no_owner_only_data(text: str) -> None:
    for marker in OWNER_ONLY_MARKERS:
        assert marker not in text


# --- auth matrix ----------------------------------------------------------------------------


@pytest.mark.parametrize(("method", "path", "body"), ROUTES, ids=ROUTE_IDS)
def test_anonymous_is_401_and_writes_nothing(client, session_local, method, path, body):
    before = _counts(session_local)
    response = _call(client, method, path, body)
    assert response.status_code == 401, response.text
    _assert_no_owner_only_data(response.text)
    assert _counts(session_local) == before


@pytest.mark.parametrize(("method", "path", "body"), ROUTES, ids=ROUTE_IDS)
def test_invalid_credentials_are_401(
    client, session_local, supabase, owner_token, method, path, body
):
    before = _counts(session_local)
    assert (
        _call(client, method, path, body, {"X-API-Key": "wrong-key"}).status_code == 401
    )
    tampered = owner_token[:-1] + ("1" if owner_token.endswith("0") else "0")
    assert (
        _call(
            client, method, path, body, {"Authorization": f"Bearer {tampered}"}
        ).status_code
        == 401
    )
    supabase.return_value = Mock(status_code=401, ok=False)
    response = _call(
        client,
        method,
        path,
        body,
        {"Authorization": f"Bearer {_jwt(marker='invalid')}"},
    )
    assert response.status_code == 401
    _assert_no_owner_only_data(response.text)
    assert _counts(session_local) == before


@pytest.mark.parametrize(("method", "path", "body"), ROUTES, ids=ROUTE_IDS)
def test_verified_member_gets_owner_access_required(
    client, session_local, supabase, method, path, body
):
    before = _counts(session_local)
    response = _call(client, method, path, body, {"Authorization": f"Bearer {_jwt()}"})
    assert response.status_code == 403
    assert response.json() == OWNER_ACCESS_REQUIRED_BODY
    assert supabase.called
    assert _counts(session_local) == before


@pytest.mark.parametrize("credential", ["api_key", "owner_bearer", "owner_cookie"])
@pytest.mark.parametrize(("method", "path", "body"), ROUTES, ids=ROUTE_IDS)
def test_owner_and_api_key_are_admitted(
    client, session_local, owner_token, credential, method, path, body
):
    headers = _owner_headers(client, credential, owner_token)
    response = _call(client, method, path, body, headers)
    assert response.status_code == 200, response.text


def test_auth_runs_before_lookup_and_body_validation(client, session_local, supabase):
    for path in (
        "/api/organizations/no-such-org/shows",
        "/api/shows/no-such-show/templates",
        "/api/shows/no-such-show/integrations",
    ):
        assert client.get(path).status_code == 401
        assert (
            client.get(path, headers={"Authorization": f"Bearer {_jwt()}"}).status_code
            == 403
        )
    # Malformed bodies are still 401 (not 422) for anonymous callers.
    assert (
        client.post(f"/api/shows/{SHOW_ID}/events", json={"bogus": 1}).status_code
        == 401
    )
    assert client.post("/api/organizations", json=[]).status_code == 401


def test_every_calyx_core_show_route_is_owner_only():
    """Guard: a new show-management route in calyx_core cannot ship without the gate.

    Only routes defined in calyx_core itself are checked (included sub-routers keep
    their own auth); ``/contacts`` is gated by its own change and excluded here.
    """
    checked = set()
    for route in calyx_core.router.routes:
        endpoint = getattr(route, "endpoint", None)
        if (
            getattr(endpoint, "__module__", "") != calyx_core.__name__
            or "/contacts" in route.path
        ):
            continue
        calls = {dependency.call for dependency in route.dependant.dependencies}
        assert member_auth.owner_or_member_read in calls, route.path
        assert not getattr(endpoint, member_auth.MEMBER_READABLE_ATTR, False), (
            route.path
        )
        checked.update((method, route.path) for method in route.methods)
    expected = {
        (
            method,
            path.replace(ORG_ID, "{org_id}")
            .replace(SHOW_ID, "{show_id}")
            .replace(TEMPLATE_ID, "{template_id}"),
        )
        for method, path, _ in ROUTES
    }
    assert checked == expected


# --- owner responses: fields that stay owner-only ------------------------------------------


def test_owner_show_and_file_listings_still_carry_owner_fields(client, session_local):
    headers = {"X-API-Key": API_KEY}
    shows = client.get(f"/api/organizations/{ORG_ID}/shows", headers=headers).json()
    assert [show["public_volunteer_token"] for show in shows] == [VOLUNTEER_TOKEN]
    files = client.get(f"/api/shows/{SHOW_ID}/files", headers=headers).json()
    assert (files[0]["storage_key"], files[0]["uploaded_by"]) == (STORAGE_KEY, UPLOADER)


# --- integration secret redaction ----------------------------------------------------------


def test_integration_list_masks_secrets_but_keeps_them_stored(client, session_local):
    response = client.get(
        f"/api/shows/{SHOW_ID}/integrations", headers={"X-API-Key": API_KEY}
    )
    assert response.status_code == 200
    for secret in SECRETS:
        assert secret not in response.text
    rows = {row["id"]: row for row in response.json()}
    config = json.loads(rows["integ-1"]["config_json"])
    assert config["password"] == "***"
    assert config["api_key"] == "***"
    assert config["headers"] == {"Authorization": "***", "Accept": "application/json"}
    assert config["url"] == "https://hooks.example.invalid/in?channel=show&token=***"
    assert config["smtp"] == [
        {
            "host": "smtp.example.invalid",
            "dsn": "smtp://mailer:***@smtp.example.invalid",
        }
    ]
    assert config["username"] == "synthetic-user"
    assert config["enabled_events"] == ["entry.created"]
    # A stored value that is not JSON is opaque and is masked entirely.
    assert rows["integ-org"]["config_json"] == "***"
    with session_local() as db:
        stored = db.get(IntegrationConnection, "integ-1").config_json
    assert json.loads(stored) == STORED_CONFIG


def test_integration_create_masks_secrets_in_the_response(client, session_local):
    config = {
        "token": "synthetic-new-token",
        "endpoint": "https://svc.example.invalid",
        "private_key": "pk",
    }
    response = client.post(
        f"/api/shows/{SHOW_ID}/integrations",
        json={"provider": "svc", "config_json": json.dumps(config)},
        headers={"X-API-Key": API_KEY},
    )
    assert response.status_code == 200
    assert "synthetic-new-token" not in response.text
    body = response.json()
    assert json.loads(body["config_json"]) == {
        "token": "***",
        "endpoint": "https://svc.example.invalid",
        "private_key": "***",
    }
    with session_local() as db:
        assert (
            json.loads(db.get(IntegrationConnection, body["id"]).config_json) == config
        )


def test_redact_config_json_unit_cases():
    assert redact_config_json(None) is None
    assert redact_config_json("") == ""
    assert redact_config_json("not json") == "***"
    assert json.loads(
        redact_config_json(
            json.dumps({"Secret": {"a": 1}, "keyring": "x", "X-Api-Key": "k"})
        )
    ) == {
        "Secret": "***",
        "keyring": "x",
        "X-Api-Key": "***",
    }
    assert json.loads(
        redact_config_json(json.dumps(["https://u:p@h.example.invalid/x"]))
    ) == ["https://u:***@h.example.invalid/x"]


# --- ICS ------------------------------------------------------------------------------------


def _add_event(session_local, **fields) -> None:
    with session_local() as db:
        db.add(
            Event(
                show_id=SHOW_ID,
                starts_at=datetime.fromisoformat("2027-03-13T09:00:00"),
                **fields,
            )
        )
        db.commit()


def _unfold(text: str) -> list[str]:
    return text.replace("\r\n ", "").split("\r\n")


def test_ics_crlf_injection_is_neutralized(client, session_local):
    _add_event(
        session_local,
        title="Judging\r\nEND:VEVENT\r\nBEGIN:VEVENT\r\nSUMMARY:Injected",
        location="Hall A\nATTENDEE:mailto:x@example.invalid",
        notes="Line one\rLine two; bring tags, labels \\ pens",
    )
    response = client.get(
        f"/api/shows/{SHOW_ID}/events/ics", headers={"X-API-Key": API_KEY}
    )
    assert response.status_code == 200
    text = response.text
    physical = text.split("\r\n")
    assert physical[-1] == ""  # every line, including the last, ends with CRLF
    assert "\n" not in text.replace("\r\n", "") and "\r" not in text.replace("\r\n", "")
    assert physical.count("BEGIN:VEVENT") == 1 and physical.count("END:VEVENT") == 1
    assert not any(
        line.startswith(("SUMMARY:Injected", "ATTENDEE:")) for line in physical
    )
    logical = _unfold(text)
    assert "SUMMARY:Judging\\nEND:VEVENT\\nBEGIN:VEVENT\\nSUMMARY:Injected" in logical
    assert "LOCATION:Hall A\\nATTENDEE:mailto:x@example.invalid" in logical
    assert (
        "DESCRIPTION:Line one\\nLine two\\; bring tags\\, labels \\\\ pens" in logical
    )


def test_ics_long_text_is_folded_at_75_octets(client, session_local):
    notes = "Orchidées " * 40
    _add_event(session_local, title="Long", notes=notes)
    text = client.get(
        f"/api/shows/{SHOW_ID}/events/ics", headers={"X-API-Key": API_KEY}
    ).text
    physical = text.split("\r\n")
    assert all(len(line.encode("utf-8")) <= 75 for line in physical)
    assert any(line.startswith(" ") for line in physical)
    assert f"DESCRIPTION:{notes}" in _unfold(text)


def test_ics_fold_never_splits_multibyte_characters():
    chunks = ics_fold("X:" + "é" * 100)
    assert all(len(chunk.encode("utf-8")) <= 75 for chunk in chunks)
    assert (
        "".join(chunk[1:] if index else chunk for index, chunk in enumerate(chunks))
        == "X:" + "é" * 100
    )


# --- org show create (was always 500) ------------------------------------------------------


def test_create_org_show_works_and_uses_path_organization(client, session_local):
    headers = {"X-API-Key": API_KEY}
    url = f"/api/organizations/{ORG_ID}/shows"
    response = client.post(
        url, json={"name": "Autumn Show", "start_date": "2027-10-02"}, headers=headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["organization_id"] == ORG_ID
    same = client.post(
        url,
        json={
            "name": "Same Org",
            "start_date": "2027-10-03",
            "organization_id": ORG_ID,
        },
        headers=headers,
    )
    assert same.status_code == 200 and same.json()["organization_id"] == ORG_ID
    before = _counts(session_local)
    mismatch = client.post(
        url,
        json={
            "name": "Moved",
            "start_date": "2027-10-04",
            "organization_id": OTHER_ORG_ID,
        },
        headers=headers,
    )
    assert mismatch.status_code == 422
    missing = client.post(
        "/api/organizations/no-such-org/shows",
        json={"name": "X", "start_date": "2027-10-05"},
        headers=headers,
    )
    assert missing.status_code == 404
    assert _counts(session_local) == before


# --- template render (was always 500) ------------------------------------------------------


def _render(client, template_id: str, context: dict, show_id: str = SHOW_ID):
    return client.post(
        f"/api/shows/{show_id}/templates/{template_id}/render",
        json={"context": context},
        headers={"X-API-Key": API_KEY},
    )


def test_render_uses_context_field(client, session_local):
    response = _render(client, TEMPLATE_ID, {"name": "Ada", "place": "Hall B"})
    assert response.status_code == 200, response.text
    assert response.json() == {
        "subject": "Welcome Ada",
        "body": "Dear Ada, see you at {booth} Hall B.",
    }
    assert _render(client, ORG_TEMPLATE_ID, {"name": "Ada"}).json() == {
        "subject": "",
        "body": "Org Ada",
    }


def test_render_honors_show_id(client, session_local):
    assert _render(client, OTHER_SHOW_TEMPLATE_ID, {"name": "Ada"}).status_code == 404
    assert (
        _render(
            client, TEMPLATE_ID, {"name": "Ada", "place": "B"}, show_id=OTHER_SHOW_ID
        ).status_code
        == 404
    )
    assert (
        _render(
            client, TEMPLATE_ID, {"name": "Ada"}, show_id="no-such-show"
        ).status_code
        == 404
    )
    assert _render(client, "no-such-template", {"name": "Ada"}).status_code == 404


def test_render_missing_variable_and_bad_context_are_422(client, session_local):
    missing = _render(client, TEMPLATE_ID, {"name": "Ada"})
    assert missing.status_code == 422
    assert missing.json()["detail"]["missing"] == ["place"]
    assert (
        _render(client, TEMPLATE_ID, {"name": {"nested": 1}, "place": "B"}).status_code
        == 422
    )
    assert (
        _render(client, TEMPLATE_ID, {"name": "x" * 5001, "place": "B"}).status_code
        == 422
    )


def _store_template(session_local, template_id: str, body: str) -> None:
    with session_local() as db:
        db.add(
            MessageTemplate(
                id=template_id, show_id=SHOW_ID, name=template_id, body_template=body
            )
        )
        db.commit()


def test_render_does_not_evaluate_format_specs_or_attributes(client, session_local):
    body = "{x:>50000000}|{x.__class__}|{x[0]}|{0}|{x!r}"
    _store_template(session_local, "tpl-dos", body)
    started = time.monotonic()
    response = _render(client, "tpl-dos", {"x": "v"})
    assert time.monotonic() - started < 5
    assert response.status_code == 200
    assert response.json()["body"] == body
    assert len(response.text) < 1_000


def test_render_output_is_bounded(client, session_local):
    _store_template(session_local, "tpl-amplify", "{v}" * 5_000)
    response = _render(client, "tpl-amplify", {"v": "x" * 5_000})
    assert response.status_code == 422
    assert str(MAX_RENDERED_CHARS) in response.json()["detail"]["message"]
    assert len(response.text) < 1_000


def test_template_create_rejects_oversized_templates(client, session_local):
    before = _counts(session_local)
    response = client.post(
        f"/api/shows/{SHOW_ID}/templates",
        json={"name": "huge", "body_template": "x" * (MAX_TEMPLATE_CHARS + 1)},
        headers={"X-API-Key": API_KEY},
    )
    assert response.status_code == 422
    assert _counts(session_local) == before


# --- config_json nesting and size bounds -----------------------------------------------------


def _nested_list(depth: int) -> str:
    return "[" * depth + "]" * depth


def _post_integration(client: TestClient, config_json: str):
    return client.post(
        f"/api/shows/{SHOW_ID}/integrations",
        json={"provider": "svc", "config_json": config_json},
        headers={"X-API-Key": API_KEY},
    )


def _store_integration(session_local, integration_id: str, config_json: str) -> None:
    with session_local() as db:
        db.add(
            IntegrationConnection(
                id=integration_id,
                show_id=SHOW_ID,
                provider="legacy",
                config_json=config_json,
            )
        )
        db.commit()


@pytest.mark.parametrize("depth", [MAX_CONFIG_DEPTH + 1, 600, 100_000])
def test_integration_create_rejects_deep_nesting_before_commit(
    client, session_local, depth
):
    before = _counts(session_local)
    response = _post_integration(client, _nested_list(depth))
    assert response.status_code == 422
    assert response.json()["detail"]["field"] == "config_json"
    assert _counts(session_local) == before
    listing = client.get(
        f"/api/shows/{SHOW_ID}/integrations", headers={"X-API-Key": API_KEY}
    )
    assert listing.status_code == 200


def test_integration_create_accepts_the_depth_limit(client, session_local):
    response = _post_integration(client, _nested_list(MAX_CONFIG_DEPTH))
    assert response.status_code == 200
    assert json.loads(response.json()["config_json"]) == json.loads(
        _nested_list(MAX_CONFIG_DEPTH)
    )


def test_integration_create_rejects_oversized_config(client, session_local):
    before = _counts(session_local)
    oversized = json.dumps({"note": "x" * MAX_CONFIG_JSON_CHARS})
    response = _post_integration(client, oversized)
    assert response.status_code == 422
    assert str(MAX_CONFIG_JSON_CHARS) in response.json()["detail"]["message"]
    assert _counts(session_local) == before


def test_json_nesting_depth_ignores_brackets_inside_strings():
    assert json_nesting_depth(json.dumps({"a": "[[[[{{{{", "b": [{"c": []}]})) == 4
    assert json_nesting_depth('"\\"[[["') == 0
    assert json_nesting_depth("not json [[") == 2


@pytest.mark.parametrize(
    "stored",
    [
        _nested_list(600),
        _nested_list(100_000),
        # nesting hidden inside JSON strings, one layer per level
        _nested_list(0) + json.dumps({"a": 1}),
    ],
)
def test_one_deeply_nested_stored_row_never_breaks_the_list(
    client, session_local, stored
):
    if stored.startswith("{"):
        # Each layer is a JSON string holding 8 more list levels: past MAX_REDACT_DEPTH
        # only through embedded strings (escaping doubles per layer, so few layers).
        for _ in range(6):
            wrapped: object = stored
            for _ in range(8):
                wrapped = [wrapped]
            stored = json.dumps({"inner": wrapped, "password": SECRET_PASSWORD})
    _store_integration(session_local, "integ-deep", stored)
    for _ in range(2):  # the row does not poison later requests either
        response = client.get(
            f"/api/shows/{SHOW_ID}/integrations", headers={"X-API-Key": API_KEY}
        )
        assert response.status_code == 200
        rows = {row["id"]: row for row in response.json()}
        assert set(rows) == {"integ-1", "integ-org", "integ-deep"}
        assert "***" in rows["integ-deep"]["config_json"]
        assert SECRET_PASSWORD not in response.text
        assert json.loads(rows["integ-1"]["config_json"])["password"] == "***"


def test_deep_redaction_masks_below_the_depth_bound():
    assert redact_config_json(_nested_list(5_000)) in {"***", json.dumps("***")}
    assert redact_config_json(_nested_list(100_000)) == "***"
    deep = json.loads(redact_config_json(_nested_list(MAX_REDACT_DEPTH + 10)))
    for _ in range(MAX_REDACT_DEPTH + 1):  # containers at depth 0..MAX_REDACT_DEPTH
        assert isinstance(deep, list)
        deep = deep[0]
    assert deep == "***"


def test_a_row_that_cannot_be_redacted_is_masked_not_a_500(
    client, session_local, monkeypatch
):
    real = calyx_core.redact_config_json

    def flaky(config_json):
        if config_json and "opaque-legacy" in config_json:
            raise RecursionError("synthetic")
        return real(config_json)

    monkeypatch.setattr(calyx_core, "redact_config_json", flaky)
    response = client.get(
        f"/api/shows/{SHOW_ID}/integrations", headers={"X-API-Key": API_KEY}
    )
    assert response.status_code == 200
    rows = {row["id"]: row for row in response.json()}
    assert rows["integ-org"]["config_json"] == "***"
    assert json.loads(rows["integ-1"]["config_json"])["password"] == "***"


# --- ICS: DTSTAMP, media type, Unicode line breaks ------------------------------------------


def test_ics_is_text_calendar_utf8_and_every_vevent_has_a_utc_dtstamp(
    client, session_local
):
    _add_event(session_local, title="Judging")
    _add_event(session_local, title="Awards", location="Hall Ω")
    response = client.get(
        f"/api/shows/{SHOW_ID}/events/ics", headers={"X-API-Key": API_KEY}
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/calendar; charset=utf-8"
    assert "LOCATION:Hall Ω" in response.content.decode("utf-8")
    events = response.text.split("BEGIN:VEVENT")[1:]
    assert len(events) == 2
    for event in events:
        stamps = [line for line in event.split("\r\n") if line.startswith("DTSTAMP:")]
        assert len(stamps) == 1
        assert re.fullmatch(r"DTSTAMP:\d{8}T\d{6}Z", stamps[0])


@pytest.mark.parametrize(
    "separator",
    ["\u2028", "\u2029", "\x85", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e"],
    ids=["LS", "PS", "NEL", "VT", "FF", "FS", "GS", "RS"],
)
def test_ics_unicode_line_breaks_cannot_start_a_calendar_line(
    client, session_local, separator
):
    _add_event(
        session_local,
        title=f"Judging{separator}END:VEVENT{separator}BEGIN:VEVENT",
        notes=f"a{separator}ATTENDEE:mailto:x@example.invalid",
    )
    text = client.get(
        f"/api/shows/{SHOW_ID}/events/ics", headers={"X-API-Key": API_KEY}
    ).text
    assert separator not in text
    # A consumer that splits on every Unicode line boundary sees no injected line.
    lines = _unfold(text)
    assert lines == text.replace("\r\n ", "").splitlines() + [""]
    assert lines.count("BEGIN:VEVENT") == 1 and lines.count("END:VEVENT") == 1
    assert not any(line.startswith("ATTENDEE:") for line in lines)
    assert "SUMMARY:Judging\\nEND:VEVENT\\nBEGIN:VEVENT" in lines
    assert "DESCRIPTION:a\\nATTENDEE:mailto:x@example.invalid" in lines


def test_ics_escaping_drops_c1_controls_and_strips_uid_line_breaks():
    assert ics_escape_text("a\x80b\x9fc\x7fd\te") == "abcd\te"
    assert ics_escape_text("x\r\ny\u2028z") == "x\\ny\\nz"
    assert ics_strip_line_breaks("id\u2028\x85\r\n\x9f-1") == "id-1"
    assert (
        ics_utc_timestamp(datetime(2027, 3, 13, 9, 0, 0, tzinfo=timezone.utc))
        == "20270313T090000Z"
    )
