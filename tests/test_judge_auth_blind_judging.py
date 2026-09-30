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

import json
import re
from datetime import timedelta
from pathlib import Path
from typing import Annotated

import pytest
import test_show_day_phase1 as phase1
from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import judge_auth
from app.judge_auth import JUDGE_SECRET_ENV, mentions_exhibitor, utcnow
from app.models import (
    Exhibitor,
    JudgeActionAudit,
    JudgeCredential,
    JudgingAward,
    Plant,
    Show,
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
)


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def judge_secret(monkeypatch):
    monkeypatch.setenv(JUDGE_SECRET_ENV, SECRET)
    monkeypatch.delenv("CALYX_OWNER_SESSION_SECRET", raising=False)
    monkeypatch.delenv("CALYX_OWNER_ACCESS_CODE", raising=False)


@pytest.fixture
def show(client, session_factory):
    """One show, one event with three classes, two exhibitors and three judges.

    Judges A and B cover the whole event; judge C covers only Paphiopedilum.
    One plant name embeds its exhibitor's surname.
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
    digest_calls = [c for c in calls if c != (len(SECRET), len(phase1.API_KEY))]
    assert digest_calls == [(64, 64)] * 3


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


def test_judge_cannot_read_the_owner_audit_or_exhibitors(client, show):
    token = _token(client, show, "A")
    for path in (
        "/api/judging/judge-audit",
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
    return {n.casefold() for n in needles}


def _assert_no_exhibitor_data(payload, show, route):
    needles = _exhibitor_needles(show)
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
                "updated_at",
            }, (route, where)
            continue
        text = "" if item is None else str(item)
        folded = text.casefold()
        assert not any(n in folded for n in needles), (route, where, text)
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
    by_name = {p["plant_name"]: p for p in plants}
    assert None in by_name and by_name[None]["plant_name_withheld"] is True
    assert (
        "Cattleya trianae" in by_name
        and by_name["Cattleya trianae"]["plant_name_withheld"] is False
    )


def test_blind_negative_control_the_sweep_detects_a_leak(show):
    exhibitor = show["exhibitors"][0]
    for leaked in (
        {"exhibitor_id": exhibitor["id"]},
        {"owner": exhibitor["email"].upper()},
        {"name": "Featherstonehaugh's best"},
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


def test_mentions_exhibitor_is_conservative():
    exhibitor = Exhibitor(
        id="ex-1",
        name="Rosalind Featherstonehaugh",
        email="rfeather@x.test",
        phone="555-010-4477",
    )
    assert mentions_exhibitor("Phal. Featherstonehaugh's Delight", exhibitor)
    assert mentions_exhibitor("ROSALIND's pick", exhibitor)
    assert mentions_exhibitor("from rfeather", exhibitor)
    assert mentions_exhibitor("tag 0104477", exhibitor)
    assert not mentions_exhibitor("Cattleya trianae", exhibitor)
    assert not mentions_exhibitor(None, exhibitor)


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


def test_reissue_is_owner_only_and_respects_the_lock(client, show, session_factory):
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
    for forbidden in ("DROP ", "DELETE ", "TRUNCATE", "ALTER ", "UPDATE ", "INSERT "):
        assert forbidden not in statements.replace("BEFORE UPDATE OR DELETE", ""), (
            forbidden
        )
    assert statements.count("CREATE TABLE ") == statements.count(
        "CREATE TABLE IF NOT EXISTS"
    )
    assert statements.count("CREATE INDEX ") == statements.count(
        "CREATE INDEX IF NOT EXISTS"
    )
    assert (
        "IF NOT EXISTS" in statements.split("CREATE TRIGGER")[0].rsplit("DO $$", 1)[1]
    )
    for model in (JudgeCredential, JudgeActionAudit):
        assert _sql_columns(sql, model.__tablename__) == {
            c.name for c in model.__table__.columns
        }
