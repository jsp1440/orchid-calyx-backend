"""Show Day (Phase 1) end-to-end tests against the lean show app on SQLite.

Covers one show run through the judging flow: classes, plants, QR tags and
scans, judge scorecards, the show judging lock, score validation and per-class
placements computed from submitted scorecards only.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models import JudgingAward, Show
from app.routers.show_day import _competition_ranks, tag_payload
from app.show_app import SHOW_TABLES, create_show_app

API_KEY = "show-day-test-key"
HEADERS = {"X-API-Key": API_KEY}


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine, tables=list(SHOW_TABLES))
    yield sessionmaker(bind=engine, autocommit=False, autoflush=False)
    engine.dispose()


@pytest.fixture
def client(monkeypatch, session_factory):
    monkeypatch.setenv("CALYX_API_KEY", API_KEY)
    monkeypatch.delenv("CALYX_TAG_BASE_URL", raising=False)
    app = create_show_app()

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client


def _post(client, path, body=None, **kwargs):
    response = client.post(path, json=body or {}, headers={**HEADERS, **kwargs.pop("headers", {})}, **kwargs)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def show_day(client, session_factory):
    """A show with two classes, three plants, two judges and one criterion set."""
    show = _post(client, "/api/shows", {"name": "Spring Show", "start_date": "2027-03-13"})
    event = _post(client, f"/api/shows/{show['id']}/judging/events", {"name": "Ribbon judging"})
    cattleya = _post(client, f"/api/judging/events/{event['id']}/categories", {"name": "Cattleya", "sort_order": 1})
    paph = _post(client, f"/api/judging/events/{event['id']}/categories", {"name": "Paphiopedilum", "sort_order": 2})
    grower = _post(client, "/api/exhibitors", {"name": "A. Grower <Esq>"})

    plants = [
        _post(client, f"/api/judging/events/{event['id']}/plants",
              {"exhibitor_id": grower["id"], "category_id": cattleya["id"], "name": name})
        for name in ("Cattleya trianae", "Cattleya labiata", "Cattleya walkeriana")
    ]
    paph_plant = _post(client, f"/api/judging/events/{event['id']}/plants",
                       {"exhibitor_id": grower["id"], "category_id": paph["id"], "name": "Paphiopedilum rothschildianum"})

    with session_factory() as db:
        db.add(JudgingAward(award_id="ribbon", system_id="society", award_name="Class ribbon"))
        db.commit()
    form = _post(client, "/api/judging/awards/ribbon/criteria",
                 {"criteria_name": "Form", "points_min": 0, "points_max": 50, "weighting": 1})
    color = _post(client, "/api/judging/awards/ribbon/criteria",
                  {"criteria_name": "Color", "points_min": 0, "points_max": 50, "weighting": 1})

    judges = [_post(client, "/api/judges", {"show_id": show["id"], "name": name}) for name in ("Judge A", "Judge B")]
    for judge in judges:
        _post(client, f"/api/judging/events/{event['id']}/assignments", {"judge_id": judge["id"]})
    cards = _post(client, f"/api/admin/judging_events/{event['id']}/generate_scorecards")
    return {
        "show": show, "event": event, "cattleya": cattleya, "paph": paph,
        "plants": plants, "paph_plant": paph_plant, "criteria": (form, color),
        "judges": judges, "cards": cards,
    }


def _card(ctx, plant, judge):
    return next(c for c in ctx["cards"] if c["plant_id"] == plant["id"] and c["judge_id"] == judge["id"])


def _score(client, ctx, plant, judge, form, color, submit=True):
    card = _card(ctx, plant, judge)
    judge_headers = {**HEADERS, "X-Judge-Id": judge["id"]}
    form_c, color_c = ctx["criteria"]
    response = client.put(
        f"/api/judge/scorecards/{card['id']}",
        json={"scores": [{"criterion_id": form_c["criteria_id"], "value": form},
                         {"criterion_id": color_c["criteria_id"], "value": color}]},
        headers=judge_headers,
    )
    assert response.status_code == 200, response.text
    if submit:
        response = client.post(f"/api/judge/scorecards/{card['id']}/submit", json={}, headers=judge_headers)
        assert response.status_code == 200, response.text
    return response.json()


def test_show_app_mounts_only_show_routes(client):
    paths = {route.path for route in client.app.routes}
    assert "/api/judging/events/{event_id}/class-results" in paths
    assert "/api/tiles/registry" in paths
    segments = {segment for path in paths for segment in path.split("/")}
    assert not segments & {"mission-control", "brain", "runtime", "harvesters", "learning"}
    assert client.get("/health").json() == {"status": "ok", "profile": "show"}


def test_show_day_routes_require_api_key(client, show_day):
    assert client.get(f"/api/judging/events/{show_day['event']['id']}/class-results").status_code == 401


def test_scorecards_cover_every_plant_for_every_judge(show_day):
    assert len(show_day["cards"]) == 4 * 2


def test_class_results_rank_submitted_cards_only(client, show_day):
    trianae, labiata, walkeriana = show_day["plants"]
    judge_a, judge_b = show_day["judges"]
    _score(client, show_day, trianae, judge_a, 45, 40)
    _score(client, show_day, trianae, judge_b, 43, 40)
    _score(client, show_day, labiata, judge_a, 50, 50, submit=False)  # draft only

    results = client.get(f"/api/judging/events/{show_day['event']['id']}/class-results", headers=HEADERS).json()
    cattleya = results["classes"][0]
    assert cattleya["category_name"] == "Cattleya"
    first = cattleya["entries"][0]
    assert (first["plant_id"], first["place"], first["average_total"]) == (trianae["id"], 1, 84.0)
    assert first["submitted_scorecards"] == 2 and first["pending_scorecards"] == 0
    unplaced = {e["plant_id"]: e for e in cattleya["entries"][1:]}
    assert unplaced[labiata["id"]]["place"] is None
    assert unplaced[labiata["id"]]["pending_scorecards"] == 2
    assert unplaced[walkeriana["id"]]["average_total"] is None
    assert results["classes"][1]["category_name"] == "Paphiopedilum"


def test_tied_totals_share_a_place(client, show_day):
    trianae, labiata, walkeriana = show_day["plants"]
    judge_a = show_day["judges"][0]
    _score(client, show_day, trianae, judge_a, 40, 40)
    _score(client, show_day, labiata, judge_a, 40, 40)
    _score(client, show_day, walkeriana, judge_a, 30, 30)
    entries = client.get(
        f"/api/judging/events/{show_day['event']['id']}/class-results", headers=HEADERS
    ).json()["classes"][0]["entries"]
    assert [e["place"] for e in entries] == [1, 1, 3]


def test_competition_ranks():
    assert _competition_ranks([90.0, 85.0, 85.0, 80.0]) == [1, 2, 2, 4]
    assert _competition_ranks([]) == []


def test_out_of_range_and_unknown_criteria_are_rejected(client, show_day):
    plant, judge = show_day["plants"][0], show_day["judges"][0]
    card = _card(show_day, plant, judge)
    judge_headers = {**HEADERS, "X-Judge-Id": judge["id"]}
    form_c = show_day["criteria"][0]
    too_high = client.put(f"/api/judge/scorecards/{card['id']}",
                          json={"scores": [{"criterion_id": form_c["criteria_id"], "value": 51}]},
                          headers=judge_headers)
    assert too_high.status_code == 422
    unknown = client.put(f"/api/judge/scorecards/{card['id']}",
                         json={"scores": [{"criterion_id": "no-such-criterion", "value": 5}]},
                         headers=judge_headers)
    assert unknown.status_code == 404
    legacy = client.post(f"/api/judging/plants/{plant['id']}/scores/{judge['id']}",
                         json={"scores": [{"criterion_id": form_c["criteria_id"], "value": -1}]},
                         headers=HEADERS)
    assert legacy.status_code == 422


def test_show_judging_lock_freezes_scorecards(client, show_day, session_factory):
    plant, judge = show_day["plants"][0], show_day["judges"][0]
    _score(client, show_day, plant, judge, 40, 40, submit=False)
    with session_factory() as db:
        db.get(Show, show_day["show"]["id"]).judging_locked = True
        db.commit()
    card = _card(show_day, plant, judge)
    judge_headers = {**HEADERS, "X-Judge-Id": judge["id"]}
    form_c = show_day["criteria"][0]
    save = client.put(f"/api/judge/scorecards/{card['id']}",
                      json={"scores": [{"criterion_id": form_c["criteria_id"], "value": 41}]},
                      headers=judge_headers)
    assert save.status_code == 409
    submit = client.post(f"/api/judge/scorecards/{card['id']}/submit", json={}, headers=judge_headers)
    assert submit.status_code == 409
    legacy = client.post(f"/api/judging/plants/{plant['id']}/scores/{judge['id']}",
                         json={"scores": [{"criterion_id": form_c["criteria_id"], "value": 10}]},
                         headers=HEADERS)
    assert legacy.status_code == 409


def test_scan_resolves_token_and_blind_judging_hides_exhibitor(client, show_day):
    plant = show_day["plants"][0]
    scan = client.get(f"/api/judging/scan/{plant['qr_code']}", headers=HEADERS).json()
    assert scan["plant_id"] == plant["id"]
    assert scan["category_name"] == "Cattleya"
    assert scan["exhibitor_name"] == "A. Grower <Esq>"
    assert scan["scorecards"] == {"total": 2, "submitted": 0}

    client.patch(f"/api/judging/events/{show_day['event']['id']}", json={"is_blind": True}, headers=HEADERS)
    assert client.get(f"/api/judging/scan/{plant['qr_code']}", headers=HEADERS).json()["exhibitor_name"] is None
    assert client.get("/api/judging/scan/QR-UNKNOWN", headers=HEADERS).status_code == 404


def test_qr_svg_renders(client, show_day):
    plant = show_day["plants"][0]
    response = client.get(f"/api/judging/plants/{plant['id']}/qr.svg", headers=HEADERS)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert "<svg" in response.text


def test_tag_sheet_groups_by_class_and_escapes_names(client, show_day):
    event_id = show_day["event"]["id"]
    sheet = client.get(f"/api/judging/events/{event_id}/tags", headers=HEADERS)
    assert sheet.status_code == 200
    page = sheet.text
    assert page.count('class="tag"') == 4
    assert page.index("Cattleya trianae") < page.index("Paphiopedilum rothschildianum")
    assert "A. Grower &lt;Esq&gt;" in page and "<Esq>" not in page
    assert "Cattleya &middot; #3" in page

    only_paph = client.get(f"/api/judging/events/{event_id}/tags",
                           params={"category_id": show_day["paph"]["id"]}, headers=HEADERS).text
    assert only_paph.count('class="tag"') == 1

    client.patch(f"/api/judging/events/{event_id}", json={"is_blind": True}, headers=HEADERS)
    assert "A. Grower" not in client.get(f"/api/judging/events/{event_id}/tags", headers=HEADERS).text


def test_tag_payload_uses_configured_scan_url(monkeypatch):
    monkeypatch.delenv("CALYX_TAG_BASE_URL", raising=False)
    assert tag_payload("QR-ABC") == "QR-ABC"
    monkeypatch.setenv("CALYX_TAG_BASE_URL", "https://show.example.org/scan/")
    assert tag_payload("QR-ABC") == "https://show.example.org/scan/QR-ABC"
