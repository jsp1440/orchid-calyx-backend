"""Adversarial member tests for Matrix identification (Release 1 journey 4).

Includes the independent checker's adversarial cases for PR #1647, adapted for the
repository's lint rules, plus planted-field coverage of every member route. The main
concern is locality, specimen and submitter material hidden in Matrix states, labels,
descriptions and observations. Supabase is always mocked; no network is reached.
"""

from __future__ import annotations

import base64
import json
import math
import re
import uuid
from unittest.mock import Mock

import pytest
import requests

from app import matrix_member_access
from app.matrix_member_views import (
    WITHHELD,
    member_provenance,
    member_state,
    screened_text,
)
from app.security import OWNER_SESSION_COOKIE, create_owner_session_token
from runtime.matrix_identification import Candidate
from runtime.matrix_identification_registry import (
    RegistryCharacter,
    create_registry_version,
)
from runtime.matrix_identification_session import get_session
from tests import test_member_matrix_identification as base
from tests.test_member_matrix_identification import (
    MEMBER_A,
    MEMBER_B,
    PREFIX,
    _bearer,
    _jwt,
    _member,
)

# Shared fixtures from the main member Matrix test module (same env, registry, mocks).
_env = base._env
registry = base.registry
client = base.client
owner_token = base.owner_token
supabase = base.supabase

pytestmark = pytest.mark.usefixtures("_env", "registry")


def _create(client, headers, **extra):
    body = {"registry_id": "angraecum-demo", "version": "1", **extra}
    response = client.post(f"{PREFIX}/sessions", headers=headers, json=body)
    assert response.status_code == 200, response.text
    return response.json()["session_id"]


# --- matrix state schema ---------------------------------------------------------------


def test_member_state_schema_is_explicit_and_fails_closed():
    assert member_state(True) is True
    assert member_state(None) is None
    assert member_state(300) == 300
    assert member_state(2.5) == 2.5
    assert member_state(math.inf) == WITHHELD
    assert member_state("star-shaped") == "star-shaped"
    assert member_state("x" * 121) == WITHHELD
    assert member_state(["white", "green"]) == ["white", "green"]
    assert member_state(["white", {"locality": "x"}, "near -18.9123"]) == [
        "white",
        WITHHELD,
        WITHHELD,
    ]
    assert member_state(["white"] * 51) == WITHHELD
    planted_range = {
        "min": 250,
        "max": 350,
        "specimen": "K1",
        "decimalLatitude": -18.9123,
    }
    assert member_state(planted_range) == {"min": 250, "max": 350}
    assert member_state({"min": "250", "max": 350}) == WITHHELD
    assert member_state({"min": True, "max": 350}) == WITHHELD
    assert member_state({"value": "white", "collector": "x"}) == WITHHELD
    assert member_state(object()) == WITHHELD


@pytest.mark.parametrize(
    "text",
    [
        "-18.9123",
        "near -18.91, 48.42",
        "18°55′S",
        "18 degrees south",
        "collected by someone@example.org",
        "Locality: Andasibe",
        "specimen K0001",
        "voucher 12",
        "GPS fix",
        "lat 18",
        "herbarium sheet",
    ],
)
def test_screen_withholds_locality_and_submitter_text(text):
    assert screened_text(text) == WITHHELD


@pytest.mark.parametrize(
    "text",
    [
        "white",
        "star-shaped",
        "10.5 mm",
        "3-5",
        "yellow, green",
        "Angraecum sesquipedale",
    ],
)
def test_screen_keeps_ordinary_state_and_label_text(text):
    assert screened_text(text) == text


def test_provenance_keeps_citation_scalars_only():
    shaped = member_provenance(
        {
            "source": "Flora 2026",
            "doi": "10.1234/abc.5678",
            "citation": {"locality": "x"},
            "reference": "near -18.9123",
            "collector": "x",
        }
    )
    assert shaped == {
        "source": "Flora 2026",
        "doi": "10.1234/abc.5678",
        "reference": WITHHELD,
    }


# --- planted fields across every member route -------------------------------------------

FORBIDDEN_TOKENS = (
    "PLANTED",
    "-18.91",
    "48.42",
    "18°",
    "Andasibe",
    "K0001",
    "author@example.org",
)
FORBIDDEN_WORDS = re.compile(
    r"specimen|collector|locality|latitude|longitude|voucher|gps", re.IGNORECASE
)


def _planted_registry() -> None:
    create_registry_version(
        registry_id="planted",
        version="1",
        title="Planted states",
        scope={
            "genus": "Angraecum",
            "species": "PLANTED at -18.9123, 48.4211",
            "site": "PLANTED-SITE",
        },
        characters=[
            RegistryCharacter(
                "spur_length_mm",
                "Spur length",
                value_type="numeric_range",
                weight=3,
                description="Measured on specimen K0001 at 18°55′S",
                provenance={"locality": "PLANTED-CHARPROV"},
            ),
            RegistryCharacter(
                "flower_color",
                "Colour (collected at Andasibe, lat -18.91)",
                value_type="multi_state",
            ),
            RegistryCharacter(
                "lip_shape", "Lip shape", description="Shape of the labellum."
            ),
            RegistryCharacter("column", "Column"),
        ],
        candidates=[
            Candidate(
                "t:x",
                "Xus plantedi",
                {
                    "spur_length_mm": {
                        "min": 250,
                        "max": 350,
                        "specimen": "PLANTED-SPECIMEN K0001",
                        "locality": "PLANTED-LOCALITY Andasibe",
                        "decimalLatitude": -18.9123,
                        "decimalLongitude": 48.4211,
                    },
                    "flower_color": [
                        "white",
                        "PLANTED list at -18.9123",
                        {"locality": "PLANTED-LISTDICT"},
                    ],
                    "lip_shape": "near 18°55'S 48°25'E",
                    "column": {"value": "short", "collector": "PLANTED-COLLECTOR"},
                },
                provenance={
                    "source": "ok",
                    "citation": {"locality": "PLANTED-NESTED"},
                    "gps": "PLANTED-GPS",
                },
            ),
            Candidate(
                "t:y",
                "Yus (voucher PLANTED-VOUCHER)",
                {
                    "spur_length_mm": {"min": 80, "max": 150},
                    "flower_color": ["white", "green"],
                    "lip_shape": "entire",
                },
                provenance={"source": "ok2"},
            ),
            Candidate(
                "t:z",
                "Zus ordinarius",
                {
                    "spur_length_mm": {"min": 20, "max": 30},
                    "flower_color": "green",
                    "lip_shape": "lobed",
                },
            ),
        ],
        provenance={
            "source": "x",
            "reviewer": "PLANTED-REVIEWER",
            "locality": "PLANTED-PROV",
        },
        actor="author@example.org",
    )


def _assert_clean(label: str, body: str) -> None:
    for token in FORBIDDEN_TOKENS:
        assert token not in body, (label, token, body[:3000])
    match = FORBIDDEN_WORDS.search(body)
    assert match is None, (label, match and match.group(0), body[:3000])


def test_planted_states_labels_descriptions_and_observations_never_reach_a_member(
    client, supabase
):
    _planted_registry()
    member = _member()
    bodies: list[tuple[str, str]] = []

    def record(label, response):
        assert response.status_code == 200, (label, response.text)
        bodies.append((label, response.text))
        return response.json()

    record("registry list", client.get(f"{PREFIX}/registry", headers=member))
    detail = record(
        "registry detail", client.get(f"{PREFIX}/registry/planted/1", headers=member)
    )
    created = record(
        "create",
        client.post(
            f"{PREFIX}/sessions",
            headers=member,
            json={
                "registry_id": "planted",
                "version": "1",
                "metadata": {"input_mode": "guided"},
            },
        ),
    )
    sid = created["session_id"]
    first = record(
        "evaluate empty",
        client.post(f"{PREFIX}/sessions/{sid}/evaluate", headers=member, json={}),
    )
    for character, value in (
        ("spur_length_mm", 300),
        ("flower_color", ["white"]),
        ("lip_shape", "found at -18.9123, 48.4211"),
        ("column", {"value": "short", "locality": "PLANTED-OBSDICT"}),
    ):
        record(
            f"observe {character}",
            client.post(
                f"{PREFIX}/sessions/{sid}/observations",
                headers=member,
                json={
                    "character": character,
                    "value": value,
                    "source": {"interface": "guided", "gps": "PLANTED-SRC"},
                },
            ),
        )
    evaluated = record(
        "evaluate",
        client.post(f"{PREFIX}/sessions/{sid}/evaluate", headers=member, json={}),
    )
    explained = []
    for audience in ("beginner", "intermediate", "expert"):
        for focus in ("summary", "next_observation", "candidate_comparison"):
            explained.append(
                record(
                    f"explain {audience}/{focus}",
                    client.post(
                        f"{PREFIX}/sessions/{sid}/explain",
                        headers=member,
                        json={"audience": audience, "focus": focus},
                    ),
                )
            )
    record("read", client.get(f"{PREFIX}/sessions/{sid}", headers=member))

    for label, body in bodies:
        _assert_clean(label, body)
    for payload in explained:
        _assert_clean("explain narrative", payload["narrative"]["text"])

    # What the member does get: the science, shaped, with explicit markers.
    characters = {item["character"]: item for item in detail["characters"]}
    assert characters["spur_length_mm"]["description"] == WITHHELD
    assert characters["flower_color"]["label"] == WITHHELD
    assert characters["lip_shape"]["description"] == "Shape of the labellum."
    assert first["next_observation"]["description"] == WITHHELD
    candidates = {item["taxon_id"]: item for item in evaluated["report"]["candidates"]}
    states = {
        e["character"]: e["candidate_state"] for e in candidates["t:x"]["explanations"]
    }
    assert states == {
        "spur_length_mm": {"min": 250, "max": 350},
        "flower_color": ["white", WITHHELD, WITHHELD],
        "lip_shape": WITHHELD,
        "column": WITHHELD,
    }
    assert candidates["t:y"]["scientific_name"] == WITHHELD
    assert candidates["t:x"]["provenance"] == {"source": "ok"}
    observed = {
        o["character"]: o["value"] for o in evaluated["session"]["observations"]
    }
    assert observed == {
        "spur_length_mm": 300,
        "flower_color": ["white"],
        "lip_shape": WITHHELD,
        "column": WITHHELD,
    }
    # The ranking itself is computed on the full registry; the member view only shapes it.
    stored = {
        c["taxon_id"]: c for c in get_session(sid)["latest_evaluation"]["candidates"]
    }
    assert {k: v["score"] for k, v in candidates.items()} == {
        k: v["score"] for k, v in stored.items()
    }


def test_owner_still_receives_the_unshaped_planted_registry(
    client, owner_token, supabase
):
    _planted_registry()
    owner = _bearer(owner_token)
    detail = client.get(f"{PREFIX}/registry/planted/1", headers=owner).json()
    assert (
        detail["candidates"][0]["states"]["spur_length_mm"]["locality"]
        == "PLANTED-LOCALITY Andasibe"
    )
    sid = client.post(
        f"{PREFIX}/sessions",
        headers=owner,
        json={"registry_id": "planted", "version": "1"},
    ).json()["session_id"]
    client.post(
        f"{PREFIX}/sessions/{sid}/observations",
        headers=owner,
        json={"character": "spur_length_mm", "value": 300},
    )
    evaluated = client.post(
        f"{PREFIX}/sessions/{sid}/evaluate", headers=owner, json={}
    ).json()
    assert "PLANTED-SPECIMEN K0001" in json.dumps(evaluated)


# --- checker adversarial cases (PR #1647 checker) ----------------------------------------


def test_cross_member_every_route_404_identical_and_no_mutation(client, supabase):
    a = _member(MEMBER_A)
    b = _member(MEMBER_B, "b")
    sid = _create(client, a)
    client.post(
        f"{PREFIX}/sessions/{sid}/observations",
        headers=a,
        json={"character": "flower_color", "value": "white"},
    )
    before = get_session(sid)
    ghost = str(uuid.uuid4())
    for method, suffix, body in (
        ("GET", "", None),
        ("POST", "/observations", {"character": "flower_color", "value": "green"}),
        ("POST", "/evaluate", {"limit": 5}),
        ("POST", "/explain", {"audience": "beginner"}),
    ):
        real = client.request(
            method, f"{PREFIX}/sessions/{sid}{suffix}", headers=b, json=body
        )
        fake = client.request(
            method, f"{PREFIX}/sessions/{ghost}{suffix}", headers=b, json=body
        )
        assert real.status_code == fake.status_code == 404, (suffix, real.text)
        assert real.text.replace(sid, "X") == fake.text.replace(ghost, "X")
    for method, suffix in (
        ("POST", "/reports"),
        ("GET", "/reports"),
        ("GET", "/vision/suggestions"),
    ):
        body = {} if method == "POST" else None
        assert (
            client.request(
                method, f"{PREFIX}/sessions/{sid}{suffix}", headers=b, json=body
            ).status_code
            == 403
        )
        assert (
            client.request(
                method, f"{PREFIX}/sessions/{sid}{suffix}", headers=a, json=body
            ).status_code
            == 403
        )
    after = get_session(sid)
    assert (
        after["revision"] == before["revision"]
        and after["observations"] == before["observations"]
    )
    response = client.post(
        f"{PREFIX}/registry/evaluate",
        headers=b,
        json={
            "registry_id": "angraecum-demo",
            "version": "1",
            "observations": [{"character": "flower_color", "value": "white"}],
        },
    )
    assert response.status_code == 403


def test_owner_session_invisible_and_uuid_case_variants(client, supabase, owner_token):
    owner = _bearer(owner_token)
    osid = client.post(
        f"{PREFIX}/sessions",
        headers=owner,
        json={"registry_id": "angraecum-demo", "version": "1"},
    ).json()["session_id"]
    a = _member(MEMBER_A)
    for sid in (
        osid,
        osid.upper(),
        "{" + osid + "}",
        "urn:uuid:" + osid,
        osid.replace("-", ""),
    ):
        response = client.get(f"{PREFIX}/sessions/{sid}", headers=a)
        assert response.status_code == 404, (sid, response.status_code, response.text)
    msid = _create(client, a)
    response = client.get(
        f"{PREFIX}/sessions/{msid}", headers={"X-API-Key": "test-api-key"}
    )
    assert (
        response.status_code == 200
        and response.json()["actor"] == f"supabase:{MEMBER_A}"
    )
    assert client.get(f"{PREFIX}/sessions/{msid}", headers=owner).status_code == 404


def test_actor_spoofing_via_body_headers_metadata(client, supabase):
    a = {
        **_member(MEMBER_A),
        "X-Actor": "owner",
        "X-Forwarded-User": "owner",
        "X-Orchid-Actor": "owner",
    }
    sid = _create(
        client,
        a,
        metadata={
            "actor": "owner",
            "owner": "owner",
            "created_by": "owner",
            "input_mode": "guided",
        },
        actor="owner",
    )
    client.post(
        f"{PREFIX}/sessions/{sid}/observations",
        headers=a,
        json={
            "character": "flower_color",
            "value": "white",
            "actor": "owner",
            "recorded_by": "owner",
            "source": {"recorded_by": "owner", "kind": "owner_review"},
        },
    )
    stored = get_session(sid)
    assert stored["actor"] == f"supabase:{MEMBER_A}"
    assert stored["metadata"] == {"input_mode": "guided"}
    assert all(
        o.get("recorded_by") in (None, f"supabase:{MEMBER_A}")
        for o in stored["observations"]
    )
    assert stored["observations"][0]["source"] == {"kind": "user_observation"}


def test_binding_uses_uuid_not_email(client, monkeypatch):
    def fake(url, headers=None, timeout=None):
        token = headers["Authorization"].removeprefix("Bearer ")
        payload = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
        response = Mock(status_code=200, ok=True)
        email = "shared@example.org" if payload["m"] != "e2" else "other@example.org"
        response.json.return_value = {"id": payload["sub"], "email": email}
        return response

    monkeypatch.setattr(
        "app.university.learner_auth.requests.get", Mock(side_effect=fake)
    )
    a1 = _bearer(_jwt(MEMBER_A, "e1"))
    a2 = _bearer(_jwt(MEMBER_A, "e2"))
    b = _bearer(_jwt(MEMBER_B, "e1"))
    sid = _create(client, a1)
    assert client.get(f"{PREFIX}/sessions/{sid}", headers=a2).status_code == 200
    assert client.get(f"{PREFIX}/sessions/{sid}", headers=b).status_code == 404
    assert "shared@" not in json.dumps(get_session(sid))


def test_supabase_returns_non_uuid_id_rejected(client, monkeypatch):
    response = Mock(status_code=200, ok=True)
    response.json.return_value = {"id": "owner", "email": "x@y"}
    monkeypatch.setattr(
        "app.university.learner_auth.requests.get", Mock(return_value=response)
    )
    result = client.post(
        f"{PREFIX}/sessions",
        headers=_member(),
        json={"registry_id": "angraecum-demo", "version": "1"},
    )
    assert result.status_code in (401, 503), result.text


def test_owner_shaped_tokens_never_reach_supabase(client, supabase):
    for token in ("abc." + "0" * 64, "eyJhbGciOi." + "f" * 64):
        for method, path in (
            ("GET", "/registry"),
            ("POST", "/sessions"),
            ("GET", "/contract"),
            ("POST", "/registry"),
        ):
            response = client.request(
                method,
                PREFIX + path,
                headers=_bearer(token),
                json={} if method == "POST" else None,
            )
            assert response.status_code == 401, (path, response.text)
    assert supabase.call_count == 0


def test_stale_owner_cookie_plus_member_bearer_is_member(client, supabase, monkeypatch):
    client.cookies.set(OWNER_SESSION_COOKIE, "bogus." + "a" * 64)
    a = _member(MEMBER_A)
    body = {"registry_id": "angraecum-demo", "version": "1"}
    response = client.post(f"{PREFIX}/sessions", headers=a, json=body)
    assert (
        response.status_code == 200
        and response.json().get("mine") is True
        and "actor" not in response.json()
    )
    assert get_session(response.json()["session_id"])["actor"] == f"supabase:{MEMBER_A}"
    assert client.get(f"{PREFIX}/contract", headers=a).status_code == 403
    from app import security

    token = str(create_owner_session_token("owner")["token"])
    monkeypatch.setattr(security.time, "time", lambda: 10**11)
    client.cookies.set(OWNER_SESSION_COOKIE, token)
    response = client.post(f"{PREFIX}/sessions", headers=a, json=body)
    assert response.status_code == 200 and response.json().get("mine") is True
    assert client.get(f"{PREFIX}/registry").status_code == 401


def test_member_explain_never_calls_provider(client, supabase, monkeypatch):
    import runtime.matrix_identification_explanation as explanation

    calls = []

    class Boom:
        def generate(self, **kwargs):
            calls.append(kwargs)
            raise AssertionError("provider called")

    monkeypatch.setattr(explanation, "configured_reply_provider", lambda: Boom())

    def no_net(*args, **kwargs):
        raise AssertionError("network")

    monkeypatch.setattr(requests, "post", no_net)
    monkeypatch.setattr(requests.Session, "request", no_net)
    a = _member()
    sid = _create(client, a)
    client.post(
        f"{PREFIX}/sessions/{sid}/observations",
        headers=a,
        json={"character": "flower_color", "value": "white"},
    )
    response = client.post(
        f"{PREFIX}/sessions/{sid}/explain", headers=a, json={"audience": "beginner"}
    )
    assert (
        response.status_code == 200
        and response.json()["narrative"]["provider"] == "matrix-deterministic-governed"
    )
    assert calls == []
    api = {"X-API-Key": "test-api-key"}
    osid = client.post(
        f"{PREFIX}/sessions",
        headers=api,
        json={"registry_id": "angraecum-demo", "version": "1"},
    ).json()["session_id"]
    client.post(
        f"{PREFIX}/sessions/{osid}/explain", headers=api, json={"audience": "beginner"}
    )
    assert len(calls) == 1  # positive control: the owner path does consult the provider


def test_body_cap_variants(client, supabase):
    a = _member()
    sid = _create(client, a)
    big = json.dumps({"character": "flower_color", "value": "x" * 17000}).encode()
    headers = {**a, "Content-Type": "application/json"}
    assert (
        client.post(
            f"{PREFIX}/sessions/{sid}/observations", headers=headers, content=big
        ).status_code
        == 413
    )

    def chunks():
        yield big

    assert (
        client.post(
            f"{PREFIX}/sessions/{sid}/observations", headers=headers, content=chunks()
        ).status_code
        == 413
    )
    lying = {**headers, "Content-Length": "10"}
    assert client.post(
        f"{PREFIX}/sessions/{sid}/observations", headers=lying, content=b'{"a":1}'
    ).status_code in (
        400,
        413,
        422,
    )
    api = {"X-API-Key": "test-api-key"}
    osid = client.post(
        f"{PREFIX}/sessions",
        headers=api,
        json={"registry_id": "angraecum-demo", "version": "1"},
    ).json()["session_id"]
    owner_headers = {**api, "Content-Type": "application/json"}
    assert (
        client.post(
            f"{PREFIX}/sessions/{osid}/observations", headers=owner_headers, content=big
        ).status_code
        == 200
    )


def test_rate_limit_key_not_bypassable_by_token_formatting(
    client, supabase, monkeypatch
):
    monkeypatch.setenv(matrix_member_access.SESSIONS_PER_HOUR_ENV, "3")
    body = {"registry_id": "angraecum-demo", "version": "1"}
    variants = [
        {"Authorization": f"Bearer {_jwt(MEMBER_A, 'a')}"},
        {"Authorization": f"bearer   {_jwt(MEMBER_A, 'a')}  "},
        {"Authorization": f"BEARER {_jwt(MEMBER_A, 'z1')}"},
        {"Authorization": f"Bearer {_jwt(MEMBER_A, 'z2')}"},
    ]
    codes = [
        client.post(f"{PREFIX}/sessions", headers=h, json=body).status_code
        for h in variants
    ]
    assert codes == [200, 200, 200, 429], codes
    assert (
        client.post(
            f"{PREFIX}/sessions", headers=_member(MEMBER_B, "b"), json=body
        ).status_code
        == 200
    )
    for _ in range(5):
        assert (
            client.post(
                f"{PREFIX}/sessions", headers={"X-API-Key": "test-api-key"}, json=body
            ).status_code
            == 200
        )


def test_write_limit_counts_each_request_once(client, supabase, monkeypatch):
    monkeypatch.setenv(matrix_member_access.WRITES_PER_MINUTE_ENV, "4")
    a = _member()
    sid = _create(client, a)
    codes = [
        client.post(
            f"{PREFIX}/sessions/{sid}/evaluate", headers=a, json={"limit": 5}
        ).status_code
        for _ in range(5)
    ]
    assert codes == [200, 200, 200, 200, 429], codes


def test_flags(client, supabase, monkeypatch):
    a = _member()
    body = {"registry_id": "angraecum-demo", "version": "1"}
    monkeypatch.setenv("OC_MEMBER_READS_ENABLED", "false")
    assert client.get(f"{PREFIX}/registry", headers=a).status_code == 401
    assert client.post(f"{PREFIX}/sessions", headers=a, json=body).status_code == 401
    monkeypatch.setenv("OC_MEMBER_READS_ENABLED", "true")
    monkeypatch.setenv(matrix_member_access.MATRIX_MEMBER_ENV, "false")
    assert client.get(f"{PREFIX}/registry", headers=a).status_code == 403
    assert client.post(f"{PREFIX}/sessions", headers=a, json=body).status_code == 403
    assert (
        client.get(
            f"{PREFIX}/registry", headers={"X-API-Key": "test-api-key"}
        ).status_code
        == 200
    )
