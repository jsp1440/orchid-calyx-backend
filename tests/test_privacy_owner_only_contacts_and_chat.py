"""Privacy: show contacts and the Mission Control chat transcript are owner-only.

``/api/shows/{show_id}/contacts`` holds personal data (name, email, phone, city) and
the Mission Control operator transcript holds whatever the operator typed to Calyx.
Both reads and every write that feeds them require the owner session or the API key.
On the contacts routes a verified member gets 403 OWNER_ACCESS_REQUIRED
(``owner_or_member_read``). The chat routes use ``verify_owner_or_api_key`` like the
rest of the chat router (no member contract for chat), so a member bearer gets 401
there. Anonymous and invalid credentials get 401 before any lookup or body
validation, and no non-owner response carries a contact field or transcript text. ``/brain/mission-control/chat/status`` stays public
(it reports only a message count and flags). Supabase is always mocked.
"""

from __future__ import annotations

import base64
import json
import time
from datetime import date
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import member_auth
from app.database import get_db
from app.main import app
from app.models import Contact, Organization, Show
from app.routers.calyx_operator_chat import reset_chat_for_tests
from app.security import OWNER_SESSION_COOKIE, create_owner_session_token

SUPABASE_GET = "app.university.learner_auth.requests.get"
MEMBER_UUID = "33333333-3333-3333-3333-333333333333"
API_KEY = "test-api-key"
OWNER_ACCESS_REQUIRED_BODY = {
    "detail": {
        "code": "OWNER_ACCESS_REQUIRED",
        "message": "This view is limited to owner access",
    }
}
CONTACT_OUT_KEYS = {
    "id",
    "organization_id",
    "show_id",
    "name",
    "email",
    "phone",
    "city",
    "contact_type",
    "created_at",
}
# Clearly synthetic personal data; used only to prove it never reaches a non-owner.
SEEDED_NAME = "Synthetic Contact Person"
SEEDED_EMAIL = "synthetic.contact@example.invalid"
SEEDED_PHONE = "+1-555-0100"
SEEDED_CITY = "Synthetic City"
PII_MARKERS = (SEEDED_NAME, SEEDED_EMAIL, SEEDED_PHONE, SEEDED_CITY)
SHOW_ID = "show-privacy-1"
ORG_ID = "org-privacy-1"
CONTACTS_URL = f"/api/shows/{SHOW_ID}/contacts"
MISSING_SHOW_URL = "/api/shows/no-such-show/contacts"
NEW_CONTACT = {
    "name": "Injected Person",
    "email": "injected@example.invalid",
    "phone": "555-0199",
    "city": "Nowhere",
}

CHAT = "/brain/mission-control/chat"
OPERATOR_TEXT = "Synthetic operator note that must stay private"


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
    reset_chat_for_tests()
    yield
    reset_chat_for_tests()
    member_auth.clear_member_token_cache()


@pytest.fixture
def session_local():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    for model in (Organization, Show, Contact):
        model.__table__.create(engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    with factory() as db:
        db.add(Organization(id=ORG_ID, name="Synthetic Orchid Society"))
        db.add(
            Show(
                id=SHOW_ID,
                organization_id=ORG_ID,
                name="Synthetic Show",
                start_date=date(2027, 3, 13),
            )
        )
        db.add(
            Contact(
                id="contact-1",
                show_id=SHOW_ID,
                name=SEEDED_NAME,
                email=SEEDED_EMAIL,
                phone=SEEDED_PHONE,
                city=SEEDED_CITY,
            )
        )
        db.add(
            Contact(
                id="contact-org",
                organization_id=ORG_ID,
                name="Org-wide Synthetic Contact",
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


def _contact_count(session_local) -> int:
    with session_local() as db:
        return db.query(Contact).count()


def _assert_no_pii(text: str) -> None:
    for marker in PII_MARKERS:
        assert marker not in text


# --- contacts: read -----------------------------------------------------------------------


def test_anonymous_contacts_read_is_401_without_pii_or_existence_leak(
    client, session_local
):
    response = client.get(CONTACTS_URL)
    assert response.status_code == 401
    _assert_no_pii(response.text)
    # Auth runs before the show lookup: a missing show is 401, not 404.
    assert client.get(MISSING_SHOW_URL).status_code == 401


def test_invalid_credentials_on_contacts_read_are_401(
    client, session_local, supabase, owner_token
):
    assert (
        client.get(CONTACTS_URL, headers={"X-API-Key": "wrong-key"}).status_code == 401
    )
    tampered = owner_token[:-1] + ("1" if owner_token.endswith("0") else "0")
    response = client.get(CONTACTS_URL, headers={"Authorization": f"Bearer {tampered}"})
    assert response.status_code == 401
    supabase.return_value = Mock(status_code=401, ok=False)
    response = client.get(
        CONTACTS_URL, headers={"Authorization": f"Bearer {_jwt(marker='invalid')}"}
    )
    assert response.status_code == 401
    _assert_no_pii(response.text)


def test_verified_member_contacts_read_gets_owner_access_required(
    client, session_local, supabase
):
    response = client.get(CONTACTS_URL, headers={"Authorization": f"Bearer {_jwt()}"})
    assert response.status_code == 403
    assert response.json() == OWNER_ACCESS_REQUIRED_BODY
    assert supabase.called
    missing = client.get(
        MISSING_SHOW_URL, headers={"Authorization": f"Bearer {_jwt()}"}
    )
    assert missing.status_code == 403 and missing.json() == OWNER_ACCESS_REQUIRED_BODY


@pytest.mark.parametrize("credential", ["api_key", "owner_bearer", "owner_cookie"])
def test_owner_and_api_key_read_contacts(
    client, session_local, owner_token, credential
):
    headers = _owner_headers(client, credential, owner_token)
    response = client.get(CONTACTS_URL, headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert {row["id"] for row in body} == {"contact-1", "contact-org"}
    assert all(set(row) == CONTACT_OUT_KEYS for row in body)
    seeded = next(row for row in body if row["id"] == "contact-1")
    assert (seeded["email"], seeded["phone"], seeded["city"]) == (
        SEEDED_EMAIL,
        SEEDED_PHONE,
        SEEDED_CITY,
    )
    assert client.get(MISSING_SHOW_URL, headers=headers).status_code == 404


# --- contacts: write ----------------------------------------------------------------------


def test_anonymous_contact_create_is_401_and_stores_nothing(client, session_local):
    before = _contact_count(session_local)
    response = client.post(CONTACTS_URL, json=NEW_CONTACT)
    assert response.status_code == 401
    assert "Injected Person" not in response.text
    # Auth runs before body validation and the show lookup.
    assert client.post(CONTACTS_URL, json={"unexpected": True}).status_code == 401
    assert client.post(MISSING_SHOW_URL, json=NEW_CONTACT).status_code == 401
    assert _contact_count(session_local) == before


def test_verified_member_contact_create_gets_owner_access_required(
    client, session_local, supabase
):
    before = _contact_count(session_local)
    response = client.post(
        CONTACTS_URL, json=NEW_CONTACT, headers={"Authorization": f"Bearer {_jwt()}"}
    )
    assert response.status_code == 403
    assert response.json() == OWNER_ACCESS_REQUIRED_BODY
    assert _contact_count(session_local) == before


def test_invalid_api_key_contact_create_is_401(client, session_local):
    before = _contact_count(session_local)
    assert (
        client.post(
            CONTACTS_URL, json=NEW_CONTACT, headers={"X-API-Key": "wrong-key"}
        ).status_code
        == 401
    )
    assert _contact_count(session_local) == before


@pytest.mark.parametrize("credential", ["api_key", "owner_bearer", "owner_cookie"])
def test_owner_and_api_key_create_contacts(
    client, session_local, owner_token, credential
):
    headers = _owner_headers(client, credential, owner_token)
    response = client.post(CONTACTS_URL, json=NEW_CONTACT, headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == CONTACT_OUT_KEYS
    assert body["show_id"] == SHOW_ID and body["email"] == NEW_CONTACT["email"]
    assert _contact_count(session_local) == 3
    assert (
        client.post(MISSING_SHOW_URL, json=NEW_CONTACT, headers=headers).status_code
        == 404
    )
    assert (
        client.post(
            CONTACTS_URL, json={"email": "no-name@example.invalid"}, headers=headers
        ).status_code
        == 422
    )


# --- Mission Control chat transcript ------------------------------------------------------


def _seed_transcript(client: TestClient) -> None:
    response = client.post(
        f"{CHAT}/messages",
        json={"content": OPERATOR_TEXT},
        headers={"X-API-Key": API_KEY},
    )
    assert response.status_code == 200, response.text


def test_anonymous_transcript_read_is_401_without_content(client, session_local):
    _seed_transcript(client)
    response = client.get(f"{CHAT}/transcript")
    assert response.status_code == 401
    assert OPERATOR_TEXT not in response.text


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/messages", {"content": "anonymous injection"}),
        (
            "/replies",
            {"content": "anonymous fake Calyx reply", "proposed_action": "merge"},
        ),
    ],
)
def test_anonymous_and_member_transcript_writes_are_rejected(
    client, session_local, supabase, path, payload
):
    assert client.post(f"{CHAT}{path}", json=payload).status_code == 401
    # Auth runs before body validation: an empty message is 401, not 422.
    assert client.post(f"{CHAT}{path}", json={"content": ""}).status_code == 401
    assert (
        client.post(
            f"{CHAT}{path}", json=payload, headers={"X-API-Key": "wrong-key"}
        ).status_code
        == 401
    )
    # No member contract for chat: a verified member bearer is a non-owner credential.
    member = client.post(
        f"{CHAT}{path}", json=payload, headers={"Authorization": f"Bearer {_jwt()}"}
    )
    assert member.status_code == 401
    transcript = client.get(f"{CHAT}/transcript", headers={"X-API-Key": API_KEY}).json()
    assert transcript == {"messages": []}
    assert client.get(f"{CHAT}/status").json()["message_count"] == 0


def test_verified_member_transcript_read_is_401(client, session_local, supabase):
    _seed_transcript(client)
    response = client.get(
        f"{CHAT}/transcript", headers={"Authorization": f"Bearer {_jwt()}"}
    )
    assert response.status_code == 401
    assert OPERATOR_TEXT not in response.text
    # The chat gate never consults Supabase: members have no chat contract.
    assert not supabase.called


@pytest.mark.parametrize("credential", ["api_key", "owner_bearer", "owner_cookie"])
def test_owner_and_api_key_round_trip_the_transcript(
    client, session_local, owner_token, credential
):
    headers = _owner_headers(client, credential, owner_token)
    message = client.post(
        f"{CHAT}/messages", json={"content": OPERATOR_TEXT}, headers=headers
    )
    assert message.status_code == 200, message.text
    reply = client.post(
        f"{CHAT}/replies",
        json={"content": "Draft prepared.", "proposed_action": "create-draft-pr"},
        headers=headers,
    )
    assert reply.status_code == 200 and reply.json()["requires_approval"] is True
    transcript = client.get(f"{CHAT}/transcript", headers=headers)
    assert transcript.status_code == 200
    messages = transcript.json()["messages"]
    assert [m.get("role") for m in messages] == ["operator", None]
    assert messages[0]["content"] == OPERATOR_TEXT
    assert (
        client.post(
            f"{CHAT}/messages", json={"content": ""}, headers=headers
        ).status_code
        == 422
    )


def test_chat_status_stays_public_and_carries_no_transcript_text(client, session_local):
    _seed_transcript(client)
    response = client.get(f"{CHAT}/status")
    assert response.status_code == 200
    assert response.json()["message_count"] == 1
    assert OPERATOR_TEXT not in response.text
