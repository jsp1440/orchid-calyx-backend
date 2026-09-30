"""Gate 8: per-judge credentials and server-side blind judging.

Runs the lean show app on in-memory SQLite (the Show Day Phase 1 fixtures).
Every exhibitor, judge and plant below is a labelled synthetic test shape; no
real show data is used.

Evidence covered: credential issuance, rotation, revocation and expiry; the
owner key is not needed on judge routes and a judge token opens no owner
route; judges cannot read or write another judge's cards; X-Judge-Id is
ignored for judges; every judge-reachable route is swept for exhibitor data
in a blind event; the show lock refuses judge writes; audit rows are written
without exhibitor data; the secret-unset case fails closed; comparison is
constant-time; tag tokens are random and legacy tokens are refused in blind
events; the SQL migration is additive, idempotent and matches the models.
"""

import hashlib
import json
import re
import unicodedata
from datetime import timedelta
from pathlib import Path
from typing import Annotated

import pytest
import test_show_day_phase1 as phase1
from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError, InternalError

from app import judge_auth
from app.judge_auth import (
    AUTH_FAILURE_BRAKE,
    JUDGE_SECRET_ENV,
    exhibitor_mention_reasons,
    utcnow,
)
from app.models import (
    Exhibitor,
    JudgeActionAudit,
    JudgeCredential,
    JudgingAward,
    Plant,
    Show,
    ShowOwnerAudit,
)
from app.routers.show_day import legacy_qr_token
from app.security import (
    OWNER_SESSION_COOKIE,
    create_owner_session_token,
    verify_api_key,
    verify_owner_or_api_key,
)

HEADERS = phase1.HEADERS
_post = phase1._post
session_factory = phase1.session_factory
client = phase1.client

SECRET = "judge-token-secret-for-tests-0123456789abcdef"
OWNER_SESSION_SECRET = "owner-session-secret-for-tests-0123456789"
PORTAL = "/api/judge-portal"

# Synthetic exhibitors whose every field is distinctive enough to find anywhere.
EXHIBITORS = (
    {
        "name": "Rosalind Featherstonehaugh",
        "email": "rfeather@exhibitor-one.test",
        "phone": "+1 (555) 010-4477",
    },
    {
        "name": "Bartholomew Quince",
        "email": "bquince@exhibitor-two.test",
        "phone": "555-010-9921",
    },
    {
        "name": "José Álvarez",
        "email": "jalvarez@alvarez-orchids.test",
        "phone": "555-010-3388",
    },
)


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def judge_secret(monkeypatch):
    monkeypatch.setenv(JUDGE_SECRET_ENV, SECRET)
    monkeypatch.delenv("CALYX_OWNER_SESSION_SECRET", raising=False)
    monkeypatch.delenv("CALYX_OWNER_ACCESS_CODE", raising=False)
    AUTH_FAILURE_BRAKE.reset()
    yield
    AUTH_FAILURE_BRAKE.reset()


@pytest.fixture
def show(client, session_factory):
    """One show, one event with three classes, two exhibitors and three judges.

    Judges A and B cover the whole event; judge C covers only Paphiopedilum.
    Two plant names embed their exhibitor's name, one without its accents.
    """
    show = _post(
        client, "/api/shows", {"name": "Spring Show", "start_date": "2027-03-13"}
    )
    event = _post(
        client, f"/api/shows/{show['id']}/judging/events", {"name": "Ribbon judging"}
    )
    classes = {
        name: _post(
            client,
            f"/api/judging/events/{event['id']}/categories",
            {"name": name, "sort_order": n},
        )
        for n, name in enumerate(("Cattleya", "Phalaenopsis", "Paphiopedilum"))
    }
    exhibitors = [_post(client, "/api/exhibitors", body) for body in EXHIBITORS]
    specs = (
        (0, "Cattleya", "Cattleya trianae"),
        (1, "Cattleya", "Cattleya labiata"),
        (0, "Phalaenopsis", "Phal. Featherstonehaugh's Delight"),
        (1, "Paphiopedilum", "Paphiopedilum rothschildianum"),
        (2, "Cattleya", "Cattleya Jose Alvarez Gold"),
    )
    plants = [
        _post(
            client,
            f"/api/judging/events/{event['id']}/plants",
            {
                "exhibitor_id": exhibitors[i]["id"],
                "category_id": classes[c]["id"],
                "name": name,
                "notes": "bench 4",
            },
        )
        for i, c, name in specs
    ]
    with session_factory() as db:
        db.add(
            JudgingAward(
                award_id="ribbon", system_id="society", award_name="Class ribbon"
            )
        )
        db.commit()
    form = _post(
        client,
        "/api/judging/awards/ribbon/criteria",
        {"criteria_name": "Form", "points_min": 0, "points_max": 50, "weighting": 1},
    )
    judges = {
        n: _post(client, "/api/judges", {"show_id": show["id"], "name": f"Judge {n}"})
        for n in "ABC"
    }
    _post(
        client,
        f"/api/judging/events/{event['id']}/assignments",
        {"judge_id": judges["A"]["id"]},
    )
    _post(
        client,
        f"/api/judging/events/{event['id']}/assignments",
        {"judge_id": judges["B"]["id"]},
    )
    _post(
        client,
        f"/api/judging/events/{event['id']}/assignments",
        {"judge_id": judges["C"]["id"], "category_id": classes["Paphiopedilum"]["id"]},
    )
    cards = _post(
        client, f"/api/admin/judging_events/{event['id']}/generate_scorecards"
    )
    return {
        "show": show,
        "event": event,
        "classes": classes,
        "exhibitors": exhibitors,
        "plants": plants,
        "form": form,
        "judges": judges,
        "cards": cards,
    }


def _issue(client, judge, **body):
    response = client.post(
        f"/api/judges/{judge['id']}/credentials", json=body, headers=HEADERS
    )
    assert response.status_code == 200, response.text
    return response.json()


def _token(client, ctx, name, **body):
    return _issue(client, ctx["judges"][name], **body)["token"]


def _get(client, path, token, **kwargs):
    return client.get(
        path, headers={**_bearer(token), **kwargs.pop("headers", {})}, **kwargs
    )


def _set_blind(client, ctx, blind=True):
    response = client.patch(
        f"/api/judging/events/{ctx['event']['id']}",
        json={"is_blind": blind},
        headers=HEADERS,
    )
    assert response.status_code == 200 and response.json()["is_blind"] is blind


def _handles(client, ctx, token):
    response = _get(client, f"{PORTAL}/events/{ctx['event']['id']}/scorecards", token)
    assert response.status_code == 200, response.text
    return [card["scorecard_handle"] for card in response.json()]


def _save(client, ctx, token, handle, value):
    body = {"scores": [{"criterion_id": ctx["form"]["criteria_id"], "value": value}]}
    return client.put(
        f"{PORTAL}/scorecards/{handle}", json=body, headers=_bearer(token)
    )


# ── Issuance, rotation, revocation, expiry ────────────────────────


def test_token_is_shown_once_and_only_a_keyed_hash_is_stored(
    client, show, session_factory
):
    issued = _issue(client, show["judges"]["A"], label="tablet 1")
    token = issued["token"]
    assert token.startswith("ocj_") and "." not in token
    assert issued["token_type"] == "Bearer" and issued["state"] == "active"
    with session_factory() as db:
        row = db.get(JudgeCredential, issued["credential_id"])
        stored = [getattr(row, c.name) for c in JudgeCredential.__table__.columns]
    assert token not in [str(v) for v in stored]
    assert re.fullmatch(r"[0-9a-f]{64}", row.token_hash)
    listed = client.get(
        f"/api/judges/{show['judges']['A']['id']}/credentials", headers=HEADERS
    ).json()
    assert len(listed) == 1
    assert "token" not in listed[0] and "token_hash" not in json.dumps(listed)
    assert token not in json.dumps(listed)


def test_judge_token_works_without_owner_key(client, show):
    token = _token(client, show, "A")
    me = _get(client, f"{PORTAL}/me", token)
    assert me.status_code == 200, me.text
    assert me.json()["judge_id"] == show["judges"]["A"]["id"]
    assert me.json()["show_id"] == show["show"]["id"]


def test_owner_key_does_not_open_judge_routes(client, show):
    _token(client, show, "A")  # a live credential exists, so nothing is vacuous
    assert client.get(f"{PORTAL}/me", headers=HEADERS).status_code == 401
    assert (
        client.get(
            f"{PORTAL}/me", headers={**HEADERS, "X-Judge-Id": show["judges"]["A"]["id"]}
        ).status_code
        == 401
    )
    assert client.get(f"{PORTAL}/me").status_code == 401


def test_rotation_revokes_the_previous_credential(client, show):
    first = _token(client, show, "A")
    second = _token(client, show, "A")
    assert _get(client, f"{PORTAL}/me", first).status_code == 401
    assert _get(client, f"{PORTAL}/me", second).status_code == 200
    kept = _token(client, show, "A", rotate=False)
    assert _get(client, f"{PORTAL}/me", second).status_code == 200
    assert _get(client, f"{PORTAL}/me", kept).status_code == 200


def test_revoked_credential_is_refused_and_audited(client, show, session_factory):
    issued = _issue(client, show["judges"]["A"])
    revoked = client.post(
        f"/api/judge-credentials/{issued['credential_id']}/revoke", headers=HEADERS
    )
    assert revoked.status_code == 200 and revoked.json()["state"] == "revoked"
    response = _get(client, f"{PORTAL}/me", issued["token"])
    assert response.status_code == 401 and "revoked" in response.json()["detail"]
    with session_factory() as db:
        rows = db.execute(select(JudgeActionAudit)).scalars().all()
    assert [(r.action, r.outcome, r.credential_id) for r in rows] == [
        ("authenticate", "credential_revoked", issued["credential_id"])
    ]


def test_expired_credential_is_refused(client, show, session_factory):
    issued = _issue(client, show["judges"]["A"], expires_in_minutes=5)
    assert _get(client, f"{PORTAL}/me", issued["token"]).status_code == 200
    with session_factory() as db:
        db.get(JudgeCredential, issued["credential_id"]).expires_at = (
            utcnow() - timedelta(seconds=1)
        )
        db.commit()
    response = _get(client, f"{PORTAL}/me", issued["token"])
    assert response.status_code == 401 and "expired" in response.json()["detail"]


@pytest.mark.parametrize("minutes", [0, 4, 14 * 24 * 60 + 1])
def test_credential_lifetime_is_bounded(client, show, minutes):
    response = client.post(
        f"/api/judges/{show['judges']['A']['id']}/credentials",
        json={"expires_in_minutes": minutes},
        headers=HEADERS,
    )
    assert response.status_code == 422


def test_issuance_rejects_scope_outside_the_judges_show(client, show):
    other = _post(
        client, "/api/shows", {"name": "Autumn Show", "start_date": "2027-10-02"}
    )
    other_event = _post(
        client, f"/api/shows/{other['id']}/judging/events", {"name": "Other"}
    )
    other_class = _post(
        client, f"/api/judging/events/{other_event['id']}/categories", {"name": "Vanda"}
    )
    path = f"/api/judges/{show['judges']['A']['id']}/credentials"
    assert (
        client.post(
            path, json={"event_ids": [other_event["id"]]}, headers=HEADERS
        ).status_code
        == 422
    )
    assert (
        client.post(
            path, json={"category_ids": [other_class["id"]]}, headers=HEADERS
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/judges/no-such-judge/credentials", json={}, headers=HEADERS
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    "token",
    [
        "ocj_",
        "ocj_" + "0" * 32 + "_" + "x" * 43,
        "ocj_" + "Z" * 32 + "_" + "x" * 43,
        "not-a-judge-token",
        "",
    ],
)
def test_malformed_or_unknown_tokens_are_refused(client, show, token):
    assert _get(client, f"{PORTAL}/me", token).status_code == 401


def test_tampered_token_and_wrong_scheme_are_refused(client, show):
    token = _token(client, show, "A")
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    assert _get(client, f"{PORTAL}/me", tampered).status_code == 401
    assert (
        client.get(
            f"{PORTAL}/me", headers={"Authorization": f"Basic {token}"}
        ).status_code
        == 401
    )
    assert (
        client.get(f"{PORTAL}/me", headers={"Authorization": token}).status_code == 401
    )
    assert client.get(f"{PORTAL}/me", headers={"X-API-Key": token}).status_code == 401


def test_comparison_is_constant_time_for_known_and_unknown_ids(
    client, show, monkeypatch
):
    token = _token(client, show, "A")
    calls = []
    real = judge_auth.credentials_match

    def spy(presented, expected):
        calls.append((len(presented), len(expected)))
        return real(presented, expected)

    monkeypatch.setattr(judge_auth, "credentials_match", spy)
    assert _get(client, f"{PORTAL}/me", token[:-2] + "zz").status_code == 401
    assert (
        _get(client, f"{PORTAL}/me", "ocj_" + "a" * 32 + "_" + "q" * 43).status_code
        == 401
    )
    assert _get(client, f"{PORTAL}/me", token).status_code == 200
    # Wrong secret, unknown id and the right token each cost exactly one
    # constant-time comparison of two 64-hex digests (the other calls are the
    # secret-versus-owner-credential check, which compares the configured secret).
    assert calls.count((64, 64)) == 3


# ── Fail closed on the server secret ──────────────────────────────


@pytest.mark.parametrize("value", [None, "", "too-short-secret"])
def test_unset_or_weak_secret_fails_closed(client, show, monkeypatch, value):
    token = _token(client, show, "A")
    if value is None:
        monkeypatch.delenv(JUDGE_SECRET_ENV)
    else:
        monkeypatch.setenv(JUDGE_SECRET_ENV, value)
    assert _get(client, f"{PORTAL}/me", token).status_code == 503
    assert client.get(f"{PORTAL}/me").status_code == 503
    issue = client.post(
        f"/api/judges/{show['judges']['A']['id']}/credentials", json={}, headers=HEADERS
    )
    assert issue.status_code == 503


def test_secret_equal_to_an_owner_credential_fails_closed(client, show, monkeypatch):
    token = _token(client, show, "A")
    monkeypatch.setenv("CALYX_OWNER_SESSION_SECRET", SECRET)
    assert _get(client, f"{PORTAL}/me", token).status_code == 503
    monkeypatch.delenv("CALYX_OWNER_SESSION_SECRET")
    monkeypatch.setenv(JUDGE_SECRET_ENV, phase1.API_KEY * 3)
    monkeypatch.setenv("CALYX_API_KEY", phase1.API_KEY * 3)
    assert _get(client, f"{PORTAL}/me", token).status_code == 503


def test_rotating_the_server_secret_invalidates_every_token(client, show, monkeypatch):
    token = _token(client, show, "A")
    monkeypatch.setenv(JUDGE_SECRET_ENV, SECRET + "-rotated")
    assert _get(client, f"{PORTAL}/me", token).status_code == 401


# ── Judge tokens never open owner routes ──────────────────────────


def _fill(path):
    return re.sub(r"\{[^}]+\}", "x", path)


# The show app's two deliberately anonymous routes (public feedback form and
# the tile registry); every other /api route requires the owner key.
PUBLIC_ROUTES = {("POST", "/api/feedback"), ("GET", "/api/tiles/registry")}


@pytest.mark.parametrize("owner_sessions", [False, True])
def test_judge_token_opens_no_owner_route(client, show, monkeypatch, owner_sessions):
    """Across every non-judge route of the show app, a judge token is refused
    wherever an anonymous caller is: 401 on every owner route, or 503 where the
    owner-session decoder is not configured. It never turns a refusal into a
    success. With owner sessions configured it gets exactly the anonymous status."""
    if owner_sessions:
        monkeypatch.setenv(
            "CALYX_OWNER_SESSION_SECRET", "owner-session-secret-for-tests-0123456789"
        )
    token = _token(client, show, "A")
    checked, public = 0, set()
    for route in client.app.routes:
        if not isinstance(route, APIRoute) or route.path.startswith(PORTAL):
            continue
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            path = _fill(route.path)
            anonymous = client.request(method, path, json={})
            for headers in (
                _bearer(token),
                {"X-API-Key": token},
                {**_bearer(token), "X-Judge-Id": show["judges"]["A"]["id"]},
            ):
                judged = client.request(method, path, json={}, headers=headers)
                if owner_sessions or judged.status_code != 503:
                    assert judged.status_code == anonymous.status_code, (
                        method,
                        route.path,
                        headers,
                    )
                else:
                    assert anonymous.status_code == 401, (method, route.path)
            if route.path.startswith("/api/") and anonymous.status_code != 401:
                public.add((method, route.path))
            checked += 1
    assert public == PUBLIC_ROUTES
    assert checked > 40


def test_owner_dependencies_reject_a_judge_token(client, show, monkeypatch):
    monkeypatch.setenv(
        "CALYX_OWNER_SESSION_SECRET", "owner-session-secret-for-tests-0123456789"
    )
    token = _token(client, show, "A")
    owner_app = FastAPI()

    @owner_app.get("/key", dependencies=[Depends(verify_api_key)])
    def key_only():
        return {"ok": True}

    @owner_app.get("/owner")
    def owner(actor: Annotated[dict, Depends(verify_owner_or_api_key)]):
        return actor

    with TestClient(owner_app) as owner_client:
        for headers in (_bearer(token), {"X-API-Key": token}):
            assert owner_client.get("/key", headers=headers).status_code == 401
            assert owner_client.get("/owner", headers=headers).status_code == 401
        owner_client.cookies.set(OWNER_SESSION_COOKIE, token)
        assert owner_client.get("/owner").status_code == 401
        owner_client.cookies.clear()
        # Positive control: the owner's own credentials still pass.
        assert owner_client.get("/key", headers=HEADERS).status_code == 200
        session = create_owner_session_token("owner")["token"]
        assert owner_client.get("/owner", headers=_bearer(session)).status_code == 200


def test_judge_cannot_read_the_owner_audit_or_exhibitors(client, show, monkeypatch):
    monkeypatch.setenv("CALYX_OWNER_SESSION_SECRET", OWNER_SESSION_SECRET)
    token = _token(client, show, "A")
    for path in (
        "/api/judging/judge-audit",
        "/api/judging/owner-audit",
        "/api/exhibitors",
        f"/api/exhibitors/{show['exhibitors'][0]['id']}",
    ):
        assert _get(client, path, token).status_code == 401


# ── Isolation between judges ──────────────────────────────────────


def test_judge_a_cannot_read_or_write_judge_b_scorecards(client, show, session_factory):
    token_a, token_b = _token(client, show, "A"), _token(client, show, "B")
    b_handle = _handles(client, show, token_b)[0]
    assert _save(client, show, token_b, b_handle, 30).status_code == 200
    assert b_handle not in _handles(client, show, token_a)

    assert _get(client, f"{PORTAL}/scorecards/{b_handle}", token_a).status_code == 404
    assert _save(client, show, token_a, b_handle, 1).status_code == 404
    submit = client.post(
        f"{PORTAL}/scorecards/{b_handle}/submit", json={}, headers=_bearer(token_a)
    )
    assert submit.status_code == 404
    b_raw = next(c for c in show["cards"] if c["judge_id"] == show["judges"]["B"]["id"])
    assert (
        _get(client, f"{PORTAL}/scorecards/{b_raw['id']}", token_a).status_code == 404
    )

    b_view = _get(client, f"{PORTAL}/scorecards/{b_handle}", token_b).json()
    assert b_view["status"] == "draft" and [s["value"] for s in b_view["scores"]] == [
        30
    ]


def test_x_judge_id_spoofing_is_ignored_for_judges(client, show):
    token_a = _token(client, show, "A")
    spoof = {"X-Judge-Id": show["judges"]["B"]["id"]}
    me = _get(client, f"{PORTAL}/me", token_a, headers=spoof).json()
    assert me["judge_id"] == show["judges"]["A"]["id"]
    token_b = _token(client, show, "B")
    assert set(_handles(client, show, token_a)).isdisjoint(
        _handles(client, show, token_b)
    )
    spoofed = _get(
        client,
        f"{PORTAL}/events/{show['event']['id']}/scorecards",
        token_a,
        headers=spoof,
    ).json()
    assert [c["scorecard_handle"] for c in spoofed] == _handles(client, show, token_a)


def test_category_assignment_limits_what_a_judge_sees(client, show):
    token_c = _token(client, show, "C")
    event_id = show["event"]["id"]
    categories = _get(client, f"{PORTAL}/events/{event_id}/categories", token_c).json()
    assert [c["name"] for c in categories] == ["Paphiopedilum"]
    plants = _get(client, f"{PORTAL}/events/{event_id}/plants", token_c).json()
    assert [p["category_name"] for p in plants] == ["Paphiopedilum"]
    assert len(_handles(client, show, token_c)) == 1
    cattleya = show["plants"][0]
    assert (
        _get(client, f"{PORTAL}/scan/{cattleya['qr_code']}", token_c).status_code == 404
    )
    other = _get(
        client,
        f"{PORTAL}/events/{event_id}/plants",
        token_c,
        params={"category_id": show["classes"]["Cattleya"]["id"]},
    )
    assert other.status_code == 404


def test_credential_scope_narrows_the_assignment(client, show):
    event_id = show["event"]["id"]
    narrowed = _token(
        client, show, "A", category_ids=[show["classes"]["Cattleya"]["id"]]
    )
    assert [
        c["name"]
        for c in _get(client, f"{PORTAL}/events/{event_id}/categories", narrowed).json()
    ] == ["Cattleya"]
    other_event = _post(
        client,
        f"/api/shows/{show['show']['id']}/judging/events",
        {"name": "Trophy judging"},
    )
    _post(
        client,
        f"/api/judging/events/{other_event['id']}/assignments",
        {"judge_id": show["judges"]["A"]["id"]},
    )
    _post(
        client, f"/api/judging/events/{other_event['id']}/categories", {"name": "Vanda"}
    )
    wide = _token(client, show, "A", rotate=False)
    assert {e["id"] for e in _get(client, f"{PORTAL}/events", wide).json()} == {
        event_id,
        other_event["id"],
    }
    only_event = _token(client, show, "A", rotate=False, event_ids=[other_event["id"]])
    assert [e["id"] for e in _get(client, f"{PORTAL}/events", only_event).json()] == [
        other_event["id"]
    ]
    assert (
        _get(client, f"{PORTAL}/events/{event_id}/plants", only_event).status_code
        == 404
    )


def test_unassigned_judge_sees_nothing(client, show):
    judge = _post(
        client, "/api/judges", {"show_id": show["show"]["id"], "name": "Judge D"}
    )
    token = _issue(client, judge)["token"]
    assert _get(client, f"{PORTAL}/events", token).json() == []
    assert (
        _get(
            client, f"{PORTAL}/events/{show['event']['id']}/scorecards", token
        ).status_code
        == 404
    )
    assert (
        _get(client, f"{PORTAL}/scan/{show['plants'][0]['qr_code']}", token).status_code
        == 404
    )


# ── Blind projection ──────────────────────────────────────────────


def _walk(value, path="$"):
    if isinstance(value, dict):
        for key, item in value.items():
            yield f"{path}.{key}", "key", key
            yield from _walk(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk(item, f"{path}[{index}]")
    else:
        yield path, "value", value


def _fold(text):
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def _exhibitor_needles(show):
    needles = set()
    for exhibitor in show["exhibitors"]:
        needles |= {
            exhibitor["id"],
            exhibitor["name"],
            exhibitor["email"],
            exhibitor["phone"],
        }
        needles |= {
            w
            for w in re.split(
                r"\W+", exhibitor["name"] + " " + exhibitor["email"].split("@")[0]
            )
            if len(w) >= 3
        }
        needles.add(re.sub(r"\D", "", exhibitor["phone"]))
    return {_fold(n) for n in needles}


def _assert_no_exhibitor_data(payload, show, route):
    """No exhibitor field, and in a blind event no entered plant name at all."""
    needles = _exhibitor_needles(show)
    entry_names = {_fold(p["name"]) for p in show["plants"]}
    raw_ids = {p["id"] for p in show["plants"]} | {c["id"] for c in show["cards"]}
    qr_codes = {p["qr_code"] for p in show["plants"]}
    for where, kind, item in _walk(payload):
        if kind == "key":
            assert "exhibitor" not in item.lower(), (route, where)
            assert item not in {
                "plant_id",
                "notes",
                "qr_code",
                "created_at",
                "submitted_at",
                "updated_at",
            }, (route, where)
            continue
        text = "" if item is None else str(item)
        folded = _fold(text)
        assert not any(n in folded for n in needles), (route, where, text)
        assert not any(n in folded for n in entry_names), (route, where, text)
        digits = re.sub(r"\D", "", text)
        assert not any(
            len(n) >= 7 and n.isdigit() and n[-7:] in digits for n in needles
        ), (route, where, text)
        assert text not in raw_ids and text not in qr_codes, (route, where, text)


def _portal_requests(client, show, token):
    """One request per judge-portal route, keyed by (method, path template)."""
    event_id = show["event"]["id"]
    handles = _handles(client, show, token)
    phal_qr = show["plants"][2]["qr_code"]
    body = {"scores": [{"criterion_id": show["form"]["criteria_id"], "value": 20}]}
    return {
        ("GET", f"{PORTAL}/me"): ("GET", f"{PORTAL}/me", None),
        ("GET", f"{PORTAL}/events"): ("GET", f"{PORTAL}/events", None),
        ("GET", f"{PORTAL}/events/{{event_id}}/categories"): (
            "GET",
            f"{PORTAL}/events/{event_id}/categories",
            None,
        ),
        ("GET", f"{PORTAL}/events/{{event_id}}/plants"): (
            "GET",
            f"{PORTAL}/events/{event_id}/plants",
            None,
        ),
        ("GET", f"{PORTAL}/events/{{event_id}}/scorecards"): (
            "GET",
            f"{PORTAL}/events/{event_id}/scorecards",
            None,
        ),
        ("GET", f"{PORTAL}/scorecards/{{handle}}"): (
            "GET",
            f"{PORTAL}/scorecards/{handles[0]}",
            None,
        ),
        ("PUT", f"{PORTAL}/scorecards/{{handle}}"): (
            "PUT",
            f"{PORTAL}/scorecards/{handles[1]}",
            body,
        ),
        ("POST", f"{PORTAL}/scorecards/{{handle}}/submit"): (
            "POST",
            f"{PORTAL}/scorecards/{handles[2]}/submit",
            {},
        ),
        ("GET", f"{PORTAL}/scan/{{qr_token}}"): (
            "GET",
            f"{PORTAL}/scan/{phal_qr}",
            None,
        ),
        ("GET", f"{PORTAL}/criteria"): ("GET", f"{PORTAL}/criteria", None),
    }


def _portal_routes(app):
    return {
        (method, route.path)
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith(PORTAL)
        for method in route.methods
    }


def test_blind_event_leaks_no_exhibitor_data_on_any_judge_route(client, show):
    _set_blind(client, show)
    token = _token(client, show, "A")
    requests = _portal_requests(client, show, token)
    # A new judge route must be added to this sweep before it can ship.
    assert set(requests) == _portal_routes(client.app)
    for key, (method, path, body) in requests.items():
        response = client.request(method, path, json=body, headers=_bearer(token))
        assert response.status_code == 200, (key, response.text)
        _assert_no_exhibitor_data(response.json(), show, key)
    plants = _get(client, f"{PORTAL}/events/{show['event']['id']}/plants", token).json()
    assert len(plants) == len(show["plants"])
    assert all(p["plant_name"] is None and p["plant_name_withheld"] for p in plants)
    assert {p["plant_name_source"] for p in plants} == {"withheld"}


def test_blind_negative_control_the_sweep_detects_a_leak(show):
    exhibitor = show["exhibitors"][0]
    for leaked in (
        {"exhibitor_id": exhibitor["id"]},
        {"owner": exhibitor["email"].upper()},
        {"name": "Featherstonehaugh's best"},
        {"name": "Cattleya JOSE alvarez"},
        {"name": "Cattleya trianae"},
        {"contact": "call 555 010 4477"},
        {"plant_id": show["plants"][0]["id"]},
        {"tag": show["plants"][0]["qr_code"]},
    ):
        with pytest.raises(AssertionError):
            _assert_no_exhibitor_data({"plant": leaked}, show, "control")


def test_blind_lists_are_ordered_by_opaque_handle(client, show):
    _set_blind(client, show)
    token = _token(client, show, "A")
    plants = _get(client, f"{PORTAL}/events/{show['event']['id']}/plants", token).json()
    assert [p["plant_handle"] for p in plants] == sorted(
        p["plant_handle"] for p in plants
    )
    assert _handles(client, show, token) == sorted(_handles(client, show, token))
    assert all(re.fullmatch(r"p_[0-9a-f]{24}", p["plant_handle"]) for p in plants)


def test_non_blind_event_shows_exhibitor_name_but_never_ids_or_contact(client, show):
    token = _token(client, show, "A")
    plants = _get(client, f"{PORTAL}/events/{show['event']['id']}/plants", token).json()
    names = {p["exhibitor_name"] for p in plants}
    assert names == {e["name"] for e in show["exhibitors"]}
    assert "Phal. Featherstonehaugh's Delight" in {p["plant_name"] for p in plants}
    text = json.dumps(plants)
    for exhibitor in show["exhibitors"]:
        assert (
            exhibitor["id"] not in text
            and exhibitor["email"] not in text
            and exhibitor["phone"] not in text
        )
    assert all("plant_id" not in p and "exhibitor_id" not in p for p in plants)
    assert {p["notes"] for p in plants} == {"bench 4"}


def test_toggling_blind_takes_effect_on_the_next_request(client, show):
    token = _token(client, show, "A")
    url = f"{PORTAL}/events/{show['event']['id']}/plants"
    assert all("exhibitor_name" in p for p in _get(client, url, token).json())
    _set_blind(client, show)
    assert all("exhibitor_name" not in p for p in _get(client, url, token).json())


@pytest.mark.parametrize(
    ("name", "email", "text"),
    [
        ("José Álvarez", "j@x.test", "Cattleya Jose Alvarez Gold"),
        ("Rosalind Featherstonehaugh", "r@x.test", "Featherstone Delight"),
        ("Bo Li", "b@x.test", "Li's champion"),
        ("José Álvarez", "j@x.test", "Grex J.A. 2027"),
        ("Rosalind Featherstonehaugh", "r@x.test", "Rosie's pick"),
        ("A Grower", "sales@smithorchids.test", "Smithorchids select"),
        ("A Grower", "a@x.test", "tag 5550104477"),
    ],
)
def test_mention_warning_catches_the_checker_reproductions(name, email, text):
    exhibitor = Exhibitor(id="ex-1", name=name, email=email, phone="555-010-4477")
    assert exhibitor_mention_reasons(text, exhibitor), text


def test_mention_warning_ignores_unrelated_text_and_generic_mail():
    exhibitor = Exhibitor(id="ex-1", name="Bo Li", email="bo@gmail.test", phone=None)
    assert exhibitor_mention_reasons("Cattleya trianae", exhibitor) == []
    assert exhibitor_mention_reasons("Gmail special", exhibitor) == []
    assert exhibitor_mention_reasons(None, exhibitor) == []


def test_blind_event_withholds_every_entered_name_including_accent_folded(client, show):
    _set_blind(client, show)
    token = _token(client, show, "A")
    body = _get(client, f"{PORTAL}/events/{show['event']['id']}/plants", token).text
    for plant in show["plants"]:
        assert _fold(plant["name"]) not in _fold(body)
    assert "alvarez" not in _fold(body) and "bench 4" not in body


def _set_display_name(client, plant, text, **extra):
    return client.put(
        f"/api/judging/plants/{plant['id']}/blind-display-name",
        json={"blind_display_name": text, **extra},
        headers=HEADERS,
    )


def test_owner_approved_blind_display_name_is_the_only_name_judges_see(
    client, show, monkeypatch
):
    monkeypatch.setenv("CALYX_OWNER_SESSION_SECRET", OWNER_SESSION_SECRET)
    trianae, _, _, _, jose = show["plants"]
    assert _set_display_name(client, trianae, "Cattleya trianae").status_code == 200
    _set_blind(client, show)
    token = _token(client, show, "A")
    plants = _get(client, f"{PORTAL}/events/{show['event']['id']}/plants", token).json()
    shown = [p for p in plants if p["plant_name"]]
    assert [(p["plant_name"], p["plant_name_source"]) for p in shown] == [
        ("Cattleya trianae", "owner_approved")
    ]

    refused = _set_display_name(client, jose, "Cattleya Jose Alvarez Gold")
    assert refused.status_code == 409
    assert refused.json()["detail"]["warnings"]
    confirmed = _set_display_name(
        client, jose, "Cattleya Jose Alvarez Gold", confirm_despite_warnings=True
    )
    assert confirmed.status_code == 200 and confirmed.json()["warnings"]
    cleared = _set_display_name(client, trianae, None)
    assert cleared.status_code == 200 and cleared.json()["blind_display_name"] is None
    assert (
        _get(client, f"/api/judging/plants/{trianae['id']}", token).status_code == 401
    )
    route = f"/api/judging/plants/{trianae['id']}/blind-display-name"
    judge_put = client.put(
        route, json={"blind_display_name": "x"}, headers=_bearer(token)
    )
    assert judge_put.status_code == 401


def test_blind_class_description_that_names_an_exhibitor_is_withheld(
    client, show, session_factory
):
    from app.models import PlantCategory

    with session_factory() as db:
        db.get(
            PlantCategory, show["classes"]["Cattleya"]["id"]
        ).description = "Sponsored by the Alvarez family"
        db.get(
            PlantCategory, show["classes"]["Phalaenopsis"]["id"]
        ).description = "Standard and novelty types"
        db.commit()
    token = _token(client, show, "A")
    url = f"{PORTAL}/events/{show['event']['id']}/categories"
    open_view = {c["name"]: c["description"] for c in _get(client, url, token).json()}
    assert open_view["Cattleya"] == "Sponsored by the Alvarez family"
    _set_blind(client, show)
    blind = {c["name"]: c["description"] for c in _get(client, url, token).json()}
    assert blind["Cattleya"] is None
    assert blind["Phalaenopsis"] == "Standard and novelty types"


def test_handles_are_rekeyed_when_the_event_turns_blind(client, show):
    token_a, token_b = (
        _token(client, show, "A"),
        _token(client, show, "B", rotate=False),
    )
    url = f"{PORTAL}/events/{show['event']['id']}/plants"

    def handles(token):
        return {p["plant_handle"] for p in _get(client, url, token).json()}

    open_a = handles(token_a)
    assert open_a == handles(token_a)  # stable within a period
    assert open_a.isdisjoint(handles(token_b))  # judge-scoped
    _set_blind(client, show)
    blind_a = handles(token_a)
    assert blind_a.isdisjoint(open_a)
    assert set(_handles(client, show, token_a)).isdisjoint(blind_a)
    _set_blind(client, show, False)
    assert handles(token_a) == open_a
    _set_blind(client, show)
    assert handles(token_a).isdisjoint(blind_a | open_a)  # a fresh blind period


def test_blind_salt_cannot_be_set_by_the_owner_patch(client, show, session_factory):
    from app.models import JudgingEvent

    path = f"/api/judging/events/{show['event']['id']}"
    client.patch(path, json={"blind_handle_salt": "chosen"}, headers=HEADERS)
    with session_factory() as db:
        assert db.get(JudgingEvent, show["event"]["id"]).blind_handle_salt is None
    created = _post(
        client,
        f"/api/shows/{show['show']['id']}/judging/events",
        {"name": "Blind trophy", "is_blind": True},
    )
    with session_factory() as db:
        assert re.fullmatch(
            r"[0-9a-f]{32}", db.get(JudgingEvent, created["id"]).blind_handle_salt
        )


# ── Scoring, lock, closed event ───────────────────────────────────


def test_judge_scores_and_submits_own_card(client, show):
    token = _token(client, show, "C")
    (handle,) = _handles(client, show, token)
    saved = _save(client, show, token, handle, 42)
    assert saved.status_code == 200 and saved.json()["scores"][0]["value"] == 42
    submitted = client.post(
        f"{PORTAL}/scorecards/{handle}/submit",
        json={"final_comment": "fine"},
        headers=_bearer(token),
    )
    assert submitted.status_code == 200 and submitted.json()["status"] == "submitted"
    assert submitted.json()["total"] == 42.0
    assert _save(client, show, token, handle, 1).status_code == 409
    results = client.get(
        f"/api/judging/events/{show['event']['id']}/class-results", headers=HEADERS
    ).json()
    paph = next(c for c in results["classes"] if c["category_name"] == "Paphiopedilum")
    assert paph["entries"][0]["average_total"] == 42.0


def test_show_lock_refuses_judge_writes_with_409_and_audits(
    client, show, session_factory
):
    token = _token(client, show, "A")
    handle = _handles(client, show, token)[0]
    assert _save(client, show, token, handle, 10).status_code == 200
    with session_factory() as db:
        db.get(Show, show["show"]["id"]).judging_locked = True
        db.commit()
    assert _save(client, show, token, handle, 11).status_code == 409
    assert (
        client.post(
            f"{PORTAL}/scorecards/{handle}/submit", json={}, headers=_bearer(token)
        ).status_code
        == 409
    )
    assert (
        _get(client, f"{PORTAL}/scorecards/{handle}", token).json()["scores"][0][
            "value"
        ]
        == 10
    )
    with session_factory() as db:
        locked = (
            db.execute(
                select(JudgeActionAudit).where(JudgeActionAudit.outcome == "locked")
            )
            .scalars()
            .all()
        )
    assert sorted(r.action for r in locked) == [
        "autosave_scorecard",
        "submit_scorecard",
    ]
    assert all(r.http_status == 409 and r.scorecard_id for r in locked)


def test_closed_event_refuses_judge_writes(client, show):
    token = _token(client, show, "A")
    handle = _handles(client, show, token)[0]
    assert (
        client.post(
            f"/api/judging/events/{show['event']['id']}/close", headers=HEADERS
        ).status_code
        == 200
    )
    assert _save(client, show, token, handle, 10).status_code == 409


# ── Audit ─────────────────────────────────────────────────────────


def test_audit_records_judge_actions_without_exhibitor_data(
    client, show, session_factory
):
    _set_blind(client, show)
    token_a, token_b = _token(client, show, "A"), _token(client, show, "B")
    handle = _handles(client, show, token_a)[0]
    assert _save(client, show, token_a, handle, 12).status_code == 200
    b_handle = _handles(client, show, token_b)[0]
    assert _get(client, f"{PORTAL}/scorecards/{b_handle}", token_a).status_code == 404

    audit = client.get(
        "/api/judging/judge-audit",
        params={"judge_id": show["judges"]["A"]["id"]},
        headers=HEADERS,
    )
    assert audit.status_code == 200
    rows = audit.json()
    by_action = {}
    for row in rows:
        by_action.setdefault((row["action"], row["outcome"]), []).append(row)
    save = by_action[("autosave_scorecard", "ok")][0]
    assert save["judging_event_id"] == show["event"]["id"] and save["scorecard_id"]
    assert (
        save["plant_id"]
        and save["plant_handle"].startswith("p_")
        and save["created_at"]
    )
    assert save["credential_id"] and save["http_status"] == 200
    denied = by_action[("get_scorecard", "not_found")][0]
    assert denied["http_status"] == 404
    needles = _exhibitor_needles(show)
    with session_factory() as db:
        stored = db.execute(select(JudgeActionAudit)).scalars().all()
        for row in stored:
            text = " ".join(
                str(getattr(row, c.name)) for c in JudgeActionAudit.__table__.columns
            ).casefold()
            assert not any(n in text for n in needles)
            assert "exhibitor" not in text


def test_audit_is_append_only(client, show, session_factory):
    token = _token(client, show, "A")
    assert _get(client, f"{PORTAL}/me", token).status_code == 200
    with session_factory() as db:
        row = db.execute(select(JudgeActionAudit)).scalars().first()
        row.outcome = "rewritten"
        with pytest.raises(ValueError, match="append-only"):
            db.commit()
        db.rollback()
        row = db.execute(select(JudgeActionAudit)).scalars().first()
        db.delete(row)
        with pytest.raises(ValueError, match="append-only"):
            db.commit()


# ── Tag tokens ────────────────────────────────────────────────────


def test_new_plants_get_random_tag_tokens(show):
    tokens = [p["qr_code"] for p in show["plants"]]
    assert len(set(tokens)) == len(tokens)
    for plant in show["plants"]:
        assert re.fullmatch(r"QR-[0-9A-F]{20}", plant["qr_code"])
        assert plant["qr_code"] != legacy_qr_token(plant["id"])


def test_blind_scan_refuses_legacy_token_until_owner_reissues(
    client, show, session_factory
):
    plant = show["plants"][0]
    with session_factory() as db:
        db.get(Plant, plant["id"]).qr_code = legacy_qr_token(plant["id"])
        db.commit()
    token = _token(client, show, "A")
    legacy = legacy_qr_token(plant["id"])
    assert (
        _get(client, f"{PORTAL}/scan/{legacy}", token).status_code == 200
    )  # not blind yet
    _set_blind(client, show)
    assert _get(client, f"{PORTAL}/scan/{legacy}", token).status_code == 409

    reissued = client.post(
        f"/api/judging/events/{show['event']['id']}/reissue-qr-tokens", headers=HEADERS
    )
    assert reissued.status_code == 200 and reissued.json()["reissued"] == 1
    fresh = client.get(f"/api/judging/plants/{plant['id']}", headers=HEADERS).json()[
        "qr_code"
    ]
    assert fresh != legacy
    scan = _get(client, f"{PORTAL}/scan/{fresh}", token)
    assert scan.status_code == 200
    assert scan.json()["scorecard"]["scorecard_handle"] in _handles(client, show, token)
    assert (
        client.get(f"/api/judging/scan/{fresh}", headers=HEADERS).json()["plant_id"]
        == plant["id"]
    )
    assert _get(client, f"{PORTAL}/scan/{legacy}", token).status_code == 404


def test_reissue_is_owner_only_and_respects_the_lock(
    client, show, session_factory, monkeypatch
):
    monkeypatch.setenv("CALYX_OWNER_SESSION_SECRET", OWNER_SESSION_SECRET)
    path = f"/api/judging/events/{show['event']['id']}/reissue-qr-tokens"
    assert (
        client.post(path, headers=_bearer(_token(client, show, "A"))).status_code == 401
    )
    with session_factory() as db:
        db.get(Show, show["show"]["id"]).judging_locked = True
        db.commit()
    assert client.post(path, headers=HEADERS).status_code == 409


# ── Migration ─────────────────────────────────────────────────────

MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "20260930_show_judge_credentials.sql"
)


def _sql_columns(sql, table):
    body = re.search(
        rf"CREATE TABLE IF NOT EXISTS {table} \((.*?)\n\);", sql, re.DOTALL
    ).group(1)
    return {line.strip().split()[0] for line in body.strip().splitlines()}


def test_migration_is_additive_idempotent_and_matches_the_models():
    sql = MIGRATION.read_text(encoding="utf-8")
    statements = re.sub(r"--[^\n]*", "", sql).upper()
    allowed = statements.replace("BEFORE UPDATE OR DELETE", "").replace(
        "BEFORE TRUNCATE", ""
    )
    alters = re.findall(r"ALTER TABLE [^;]*;", allowed)
    assert alters == [
        "ALTER TABLE JUDGING_EVENTS ADD COLUMN IF NOT EXISTS BLIND_HANDLE_SALT VARCHAR(32);",
        "ALTER TABLE JUDGING_EVENTS ADD COLUMN IF NOT EXISTS BLIND_DISPLAY_NAME TEXT;",
        "ALTER TABLE PLANT_CATEGORIES ADD COLUMN IF NOT EXISTS BLIND_DISPLAY_NAME TEXT;",
        "ALTER TABLE PLANTS ADD COLUMN IF NOT EXISTS BLIND_DISPLAY_NAME TEXT;",
    ]
    for alter in alters:
        allowed = allowed.replace(alter, "")
    for forbidden in (
        r"\bDROP\s",
        r"\bDELETE\s+FROM\b",
        r"\bTRUNCATE\s",
        r"\bALTER\s",
        r"\bUPDATE\s+\w+\s+SET\b",
        r"\bINSERT\s+INTO\b",
    ):
        assert not re.search(forbidden, allowed), forbidden
    assert statements.count("CREATE TABLE ") == statements.count(
        "CREATE TABLE IF NOT EXISTS"
    )
    assert statements.count("CREATE INDEX ") == statements.count(
        "CREATE INDEX IF NOT EXISTS"
    )
    assert statements.count("CREATE TRIGGER %I") == 2
    assert statements.count("IF NOT EXISTS (") == 2
    assert "BEFORE TRUNCATE ON %I" in statements
    assert "ARRAY['JUDGE_ACTION_AUDIT', 'SHOW_OWNER_AUDIT']" in statements
    for model in (JudgeCredential, JudgeActionAudit, ShowOwnerAudit):
        assert _sql_columns(sql, model.__tablename__) == {
            c.name for c in model.__table__.columns
        }


# ── Append-only, beyond the unit of work ──────────────────────────


def test_bulk_update_and_delete_on_the_audit_are_refused(client, show, session_factory):
    token = _token(client, show, "A")
    assert _get(client, f"{PORTAL}/me", token).status_code == 200
    with session_factory() as db:
        with pytest.raises(ValueError, match="append-only"):
            db.execute(update(JudgeActionAudit).values(outcome="rewritten"))
        db.rollback()
        with pytest.raises(ValueError, match="append-only"):
            db.execute(delete(JudgeActionAudit))
        db.rollback()
        # SQLite's RAISE(ABORT) surfaces as IntegrityError; a PostgreSQL
        # trigger's RAISE EXCEPTION as InternalError.
        refused = {"sqlite": IntegrityError, "postgresql": InternalError}[
            db.get_bind().dialect.name
        ]
        for raw in (
            "UPDATE judge_action_audit SET outcome = 'x'",
            "DELETE FROM judge_action_audit",
        ):
            with pytest.raises(refused, match="append-only"):
                db.connection().exec_driver_sql(raw)
            db.rollback()
        assert db.execute(select(JudgeActionAudit)).scalars().first().outcome == "ok"


# ── Audit gaps and rate limits ────────────────────────────────────


def _audit_rows(session_factory, **where):
    with session_factory() as db:
        rows = db.execute(select(JudgeActionAudit)).scalars().all()
    return [r for r in rows if all(getattr(r, k) == v for k, v in where.items())]


def test_request_validation_failures_are_audited_without_the_input(
    client, show, session_factory
):
    token = _token(client, show, "A")
    handle = _handles(client, show, token)[0]
    secret_marker = "do-not-record-this-input"
    bad_shape = client.put(
        f"{PORTAL}/scorecards/{handle}",
        json={"scores": [{"criterion_id": 7, "value": secret_marker}]},
        headers=_bearer(token),
    )
    assert bad_shape.status_code == 422
    malformed = client.put(
        f"{PORTAL}/scorecards/{handle}",
        content=b"{not json " + secret_marker.encode(),
        headers={**_bearer(token), "Content-Type": "application/json"},
    )
    assert malformed.status_code == 422
    rows = _audit_rows(session_factory, outcome="invalid")
    assert [(r.action, r.http_status) for r in rows] == [
        ("autosave_scorecard", 422),
        ("autosave_scorecard", 422),
    ]
    assert rows[0].scorecard_id  # the in-route validation knows the card
    for row in rows:
        values = " ".join(
            str(getattr(row, c.name)) for c in JudgeActionAudit.__table__.columns
        )
        assert secret_marker not in values and token not in values


def test_wrong_secret_for_a_known_credential_is_audited_unknown_id_is_not(
    client, show, session_factory
):
    issued = _issue(client, show["judges"]["A"])
    wrong = issued["token"][:-4] + "abcd"
    assert _get(client, f"{PORTAL}/me", wrong).status_code == 401
    assert (
        _get(client, f"{PORTAL}/me", "ocj_" + "b" * 32 + "_" + "q" * 43).status_code
        == 401
    )
    rows = _audit_rows(session_factory, action="authenticate")
    assert [(r.outcome, r.credential_id, r.judge_id) for r in rows] == [
        ("credential_mismatch", issued["credential_id"], show["judges"]["A"]["id"])
    ]
    stored = " ".join(
        str(getattr(rows[0], c.name)) for c in JudgeActionAudit.__table__.columns
    )
    assert wrong not in stored and wrong.split("_")[-1] not in stored


def _junk(n):
    return f"ocj_{n:032x}_" + "q" * 43


def test_junk_tokens_from_the_hall_address_never_lock_out_a_valid_judge(client, show):
    """Checker attack 1: 55 junk tokens behind the hall's forwarded address."""
    good = _token(client, show, "A")
    hall = {"X-Forwarded-For": "198.51.100.20"}
    codes = [
        _get(client, f"{PORTAL}/me", _junk(n), headers=hall).status_code
        for n in range(55)
    ]
    assert set(codes) == {401, 429} and codes[0] == 401 and codes[-1] == 429
    assert _get(client, f"{PORTAL}/me", good, headers=hall).status_code == 200
    assert _get(client, f"{PORTAL}/me", good).status_code == 200


def test_bad_attempts_on_a_credential_back_off_but_never_block_its_secret(client, show):
    """Checker attack 2: 12 wrong secrets on a valid credential id."""
    issued = _issue(client, show["judges"]["A"])
    wrong = issued["token"][:-4] + "abcd"
    responses = [_get(client, f"{PORTAL}/me", wrong) for _ in range(12)]
    assert [r.status_code for r in responses[:3]] == [401] * 3
    waits = [int(r.headers["Retry-After"]) for r in responses[3:]]
    assert all(r.status_code == 429 for r in responses[3:])
    assert waits == sorted(waits) and waits[-1] > waits[0]  # exponential backoff
    elsewhere = {"X-Forwarded-For": "203.0.113.9"}
    assert (
        _get(client, f"{PORTAL}/me", issued["token"], headers=elsewhere).status_code
        == 200
    )
    assert _get(client, f"{PORTAL}/me", issued["token"]).status_code == 200


def test_rotating_forwarded_addresses_is_bounded(client, show, monkeypatch):
    """Checker attack 3: a new X-Forwarded-For and a new unknown id every time."""
    monkeypatch.setenv("JUDGE_AUTH_FAILURE_LIMIT_PER_CLIENT", "5")
    good = _token(client, show, "A")
    codes = [
        _get(
            client,
            f"{PORTAL}/me",
            _junk(n),
            headers={"X-Forwarded-For": f"203.0.113.{n}"},
        ).status_code
        for n in range(10)
    ]
    assert codes == [401] * 5 + [429] * 5  # the forged hop is ignored: one peer
    assert _get(client, f"{PORTAL}/me", good).status_code == 200


def test_global_failure_budget_bounds_rotation_behind_a_trusted_proxy(
    client, show, monkeypatch
):
    monkeypatch.setenv("JUDGE_AUTH_TRUSTED_PROXY_HOPS", "1")
    monkeypatch.setenv("JUDGE_AUTH_FAILURE_LIMIT_GLOBAL", "8")
    good = _token(client, show, "A")
    codes = [
        _get(
            client,
            f"{PORTAL}/me",
            _junk(n),
            headers={"X-Forwarded-For": f"203.0.113.{n}"},
        ).status_code
        for n in range(12)
    ]
    assert codes == [401] * 8 + [429] * 4
    assert _get(client, f"{PORTAL}/me", good).status_code == 200


def test_client_key_uses_the_peer_or_the_trusted_hop_never_a_forged_one(monkeypatch):
    from types import SimpleNamespace

    from app.judge_auth import judge_client_key

    def request(forwarded):
        return SimpleNamespace(
            client=SimpleNamespace(host="10.0.0.5"),
            headers={"x-forwarded-for": forwarded} if forwarded else {},
        )

    monkeypatch.delenv("JUDGE_AUTH_TRUSTED_PROXY_HOPS", raising=False)
    assert judge_client_key(request("1.2.3.4")) == "10.0.0.5"
    monkeypatch.setenv("JUDGE_AUTH_TRUSTED_PROXY_HOPS", "1")
    assert judge_client_key(request("6.6.6.6, 198.51.100.7")) == "198.51.100.7"
    assert judge_client_key(request(None)) == "10.0.0.5"
    monkeypatch.setenv("JUDGE_AUTH_TRUSTED_PROXY_HOPS", "2")
    assert (
        judge_client_key(request("6.6.6.6, 198.51.100.7, 10.0.0.9")) == "198.51.100.7"
    )


def test_unreadable_body_is_audited(client, show, session_factory):
    token = _token(client, show, "A")
    handle = _handles(client, show, token)[0]
    response = client.put(
        f"{PORTAL}/scorecards/{handle}",
        content=bytes([0x7B, 0x22, 0xFF, 0xFE, 0x22, 0x7D]),  # {"<not UTF-8>"}
        headers={**_bearer(token), "Content-Type": "application/json"},
    )
    assert response.status_code == 400
    rows = _audit_rows(session_factory, outcome="invalid")
    assert [(r.action, r.http_status, r.detail) for r in rows] == [
        ("autosave_scorecard", 400, "request body unreadable")
    ]


@pytest.mark.parametrize(
    "other_env",
    ["ORCHID_JUDGE_ADMIN_KEY", "ADMIN_API_KEY", "CONSTITUENT_MANAGE_SECRET"],
)
def test_secret_equal_to_an_admin_secret_fails_closed(
    client, show, monkeypatch, other_env
):
    token = _token(client, show, "A")
    monkeypatch.setenv(other_env, SECRET)
    assert _get(client, f"{PORTAL}/me", token).status_code == 503


# ── Scope edges (assignment state and show boundary) ──────────────


def test_inactive_assignment_grants_nothing(client, show):
    judge = _post(
        client, "/api/judges", {"show_id": show["show"]["id"], "name": "Judge E"}
    )
    _post(
        client,
        f"/api/judging/events/{show['event']['id']}/assignments",
        {"judge_id": judge["id"], "active": False},
    )
    token = _issue(client, judge)["token"]
    assert _get(client, f"{PORTAL}/events", token).json() == []
    url = f"{PORTAL}/events/{show['event']['id']}/plants"
    assert _get(client, url, token).status_code == 404


def test_assignment_to_another_shows_event_grants_nothing(
    client, show, session_factory
):
    from app.models import JudgeAssignment

    other = _post(
        client, "/api/shows", {"name": "Autumn Show", "start_date": "2027-10-02"}
    )
    other_event = _post(
        client, f"/api/shows/{other['id']}/judging/events", {"name": "Other"}
    )
    _post(
        client, f"/api/judging/events/{other_event['id']}/categories", {"name": "Vanda"}
    )
    # The owner API refuses this (422); a row written around it must still grant nothing.
    with session_factory() as db:
        db.add(
            JudgeAssignment(
                judging_event_id=other_event["id"],
                judge_id=show["judges"]["C"]["id"],
                active=True,
            )
        )
        db.commit()
    token = _token(client, show, "C")
    assert [e["id"] for e in _get(client, f"{PORTAL}/events", token).json()] == [
        show["event"]["id"]
    ]
    assert (
        _get(
            client, f"{PORTAL}/events/{other_event['id']}/categories", token
        ).status_code
        == 404
    )


# ── Round 2: schedule text, owner audit, owner session, timestamps ─


def _leaky_schedule(client, show, session_factory):
    """The checker's leaks: exhibitor names inside class, event and rubric text."""
    from app.models import JudgingCriterion, JudgingEvent, PlantCategory

    with session_factory() as db:
        db.get(
            PlantCategory, show["classes"]["Cattleya"]["id"]
        ).name = "Rosalind Featherstonehaugh Memorial class"
        db.get(JudgingEvent, show["event"]["id"]).name = "Featherstonehaugh Cup judging"
        db.get(
            JudgingCriterion, show["form"]["criteria_id"]
        ).criteria_description = "Form as grown by Bartholomew Quince"
        db.commit()


def test_blind_schedule_text_naming_an_exhibitor_is_withheld_everywhere(
    client, show, session_factory
):
    _leaky_schedule(client, show, session_factory)
    token = _token(client, show, "A")
    event_id = show["event"]["id"]
    urls = [
        f"{PORTAL}/events",
        f"{PORTAL}/events/{event_id}/categories",
        f"{PORTAL}/events/{event_id}/plants",
        f"{PORTAL}/events/{event_id}/scorecards",
        f"{PORTAL}/criteria",
        f"{PORTAL}/scan/{show['plants'][0]['qr_code']}",
    ]
    assert "Featherstonehaugh" in _get(client, urls[0], token).text  # open event
    _set_blind(client, show)
    for url in urls:
        body = _get(client, url, token)
        assert body.status_code == 200, url
        for word in ("featherstonehaugh", "quince", "rosalind"):
            assert word not in _fold(body.text), (url, word)
    events = _get(client, urls[0], token).json()
    assert events[0]["name"] is None and events[0]["name_withheld"] is True
    classes = {c["id"]: c for c in _get(client, urls[1], token).json()}
    memorial = classes[show["classes"]["Cattleya"]["id"]]
    assert memorial["name"] is None and memorial["name_withheld"] is True
    assert classes[show["classes"]["Paphiopedilum"]["id"]]["name"] == "Paphiopedilum"


def test_owner_blind_labels_for_class_and_event_are_shown_and_audited(
    client, show, session_factory
):
    _leaky_schedule(client, show, session_factory)
    _set_blind(client, show)
    class_id, event_id = show["classes"]["Cattleya"]["id"], show["event"]["id"]
    ok = client.put(
        f"/api/judging/categories/{class_id}/blind-display-name",
        json={"blind_display_name": "Memorial class"},
        headers=HEADERS,
    )
    assert ok.status_code == 200 and ok.json()["warnings"] == []
    refused = client.put(
        f"/api/judging/events/{event_id}/blind-display-name",
        json={"blind_display_name": "Featherstone Cup"},
        headers=HEADERS,
    )
    assert refused.status_code == 409
    assert (
        client.put(
            f"/api/judging/events/{event_id}/blind-display-name",
            json={"blind_display_name": "Spring cup"},
            headers=HEADERS,
        ).status_code
        == 200
    )
    token = _token(client, show, "A")
    names = {
        c["id"]: c["name"]
        for c in _get(client, f"{PORTAL}/events/{event_id}/categories", token).json()
    }
    assert names[class_id] == "Memorial class"
    assert _get(client, f"{PORTAL}/events", token).json()[0]["name"] == "Spring cup"
    actions = [
        r["action"]
        for r in client.get("/api/judging/owner-audit", headers=HEADERS).json()
    ]
    assert actions.count("blind_label_set") == 2 and "blind_label_refused" in actions


def test_confirmed_exhibitor_derived_label_is_audited_as_a_hash_only(
    client, show, session_factory
):
    jose = show["plants"][4]
    text = "Cattleya Jose Alvarez Gold"
    confirmed = client.put(
        f"/api/judging/plants/{jose['id']}/blind-display-name",
        json={"blind_display_name": text, "confirm_despite_warnings": True},
        headers=HEADERS,
    )
    assert (
        confirmed.status_code == 200 and confirmed.json()["confirmed_despite_warnings"]
    )
    rows = client.get("/api/judging/owner-audit", headers=HEADERS).json()
    row = next(r for r in rows if r["object_id"] == jose["id"])
    assert (
        row["action"] == "blind_label_set" and row["confirmed_despite_warnings"] is True
    )
    assert row["warnings"] and row["actor"] == "backend_api_key" and row["created_at"]
    assert row["text_value"] is None and row["text_withheld"] is True
    assert row["text_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    with session_factory() as db:
        stored = db.execute(select(ShowOwnerAudit)).scalars().all()
        dump = " ".join(
            str(getattr(r, c.name))
            for r in stored
            for c in ShowOwnerAudit.__table__.columns
        )
    assert "alvarez" not in _fold(dump)
    plain = client.put(
        f"/api/judging/plants/{show['plants'][0]['id']}/blind-display-name",
        json={"blind_display_name": "Cattleya trianae"},
        headers=HEADERS,
    )
    assert plain.status_code == 200
    rows = client.get("/api/judging/owner-audit", headers=HEADERS).json()
    assert any(
        r["text_value"] == "Cattleya trianae" and not r["confirmed_despite_warnings"]
        for r in rows
    )


def test_credential_issue_rotate_revoke_and_reissue_are_owner_audited(client, show):
    first = _issue(client, show["judges"]["A"])
    _issue(client, show["judges"]["A"])
    client.post(
        f"/api/judge-credentials/{first['credential_id']}/revoke", headers=HEADERS
    )
    client.post(
        f"/api/judging/events/{show['event']['id']}/reissue-qr-tokens", headers=HEADERS
    )
    actions = [
        r["action"]
        for r in client.get("/api/judging/owner-audit", headers=HEADERS).json()
    ]
    assert sorted(actions) == [
        "issue_credential",
        "reissue_qr_tokens",
        "rotate_credential",
    ]  # revoking an already rotated-out credential changes nothing


def test_owner_audit_is_append_only(client, show, session_factory):
    _issue(client, show["judges"]["A"])
    with session_factory() as db:
        with pytest.raises(ValueError, match="append-only"):
            db.execute(update(ShowOwnerAudit).values(actor="someone"))
        db.rollback()
        row = db.execute(select(ShowOwnerAudit)).scalars().first()
        db.delete(row)
        with pytest.raises(ValueError, match="append-only"):
            db.commit()


OWNER_ROUTES = (
    ("POST", "/api/judges/{judge}/credentials", {}),
    ("GET", "/api/judges/{judge}/credentials", None),
    ("GET", "/api/judging/judge-audit", None),
    ("GET", "/api/judging/owner-audit", None),
    ("POST", "/api/judging/events/{event}/reissue-qr-tokens", None),
    (
        "PUT",
        "/api/judging/plants/{plant}/blind-display-name",
        {"blind_display_name": "Cattleya"},
    ),
    (
        "PUT",
        "/api/judging/categories/{category}/blind-display-name",
        {"blind_display_name": "Class A"},
    ),
    (
        "PUT",
        "/api/judging/events/{event}/blind-display-name",
        {"blind_display_name": "Spring"},
    ),
    ("GET", "/api/judging/events/{event}/tags", None),
    ("GET", "/api/judging/events/{event}/class-results", None),
    ("GET", "/api/judging/scan/{qr}", None),
)


def _owner_path(show, template):
    return template.format(
        judge=show["judges"]["A"]["id"],
        event=show["event"]["id"],
        plant=show["plants"][0]["id"],
        category=show["classes"]["Cattleya"]["id"],
        qr=show["plants"][0]["qr_code"],
    )


def test_owner_session_opens_owner_routes_and_a_judge_token_does_not(
    client, show, monkeypatch
):
    from app.security import create_owner_session_token

    monkeypatch.setenv("CALYX_OWNER_SESSION_SECRET", OWNER_SESSION_SECRET)
    token = _token(client, show, "B")
    session = _bearer(create_owner_session_token("owner")["token"])
    for method, template, body in OWNER_ROUTES:
        path = _owner_path(show, template)
        judged = client.request(method, path, json=body, headers=_bearer(token))
        assert judged.status_code == 401, (method, template, judged.status_code)
        owned = client.request(method, path, json=body, headers=session)
        assert owned.status_code == 200, (method, template, owned.text)
    rows = client.get("/api/judging/owner-audit", headers=session).json()
    by_session = {r["action"] for r in rows if r["auth_type"] == "owner_session"}
    assert {"issue_credential", "reissue_qr_tokens", "blind_label_set"} <= by_session


def test_blind_scorecards_carry_no_timestamps(client, show):
    token = _token(client, show, "C")
    (handle,) = _handles(client, show, token)
    assert _save(client, show, token, handle, 30).status_code == 200
    submitted = client.post(
        f"{PORTAL}/scorecards/{handle}/submit", json={}, headers=_bearer(token)
    )
    assert submitted.json()["submitted_at"]  # open event: shown
    _set_blind(client, show)
    for card in _get(
        client, f"{PORTAL}/events/{show['event']['id']}/scorecards", token
    ).json():
        assert "submitted_at" not in card and card["status"] == "submitted"
