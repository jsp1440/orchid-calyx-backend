"""Show judging lock, event status order and blind legacy results.

Reuses the Show Day Phase 1 fixtures (lean show app on in-memory SQLite). Each
route in ``MUTATING_ROUTES`` (judging, entry and award writes) is called once before the show's judging lock (200)
and once after it (409); the lock is set and cleared through the owner's
``PATCH /api/shows`` route, which stays allowed.
"""

import pytest
import test_show_day_phase1 as phase1

HEADERS = phase1.HEADERS
_post = phase1._post
_score = phase1._score

# The Phase 1 fixtures, bound here so pytest resolves them by name.
session_factory = phase1.session_factory
client = phase1.client
show_day = phase1.show_day


def _set_lock(client, ctx, locked):
    response = client.patch(
        f"/api/shows/{ctx['show']['id']}",
        json={"judging_locked": locked},
        headers=HEADERS,
    )
    assert response.status_code == 200, response.text
    assert response.json()["judging_locked"] is locked


def _send(client, method, path, body=None):
    return client.request(method, path, json=body or {}, headers=HEADERS)


@pytest.fixture
def lock_ctx(client, show_day):
    """Resources a route needs for a fresh second call, made before the lock."""
    show_id = show_day["show"]["id"]
    extra_judges = [
        _post(client, "/api/judges", {"show_id": show_id, "name": name})
        for name in ("Judge C", "Judge D")
    ]
    entry = _post(
        client,
        "/api/entries",
        {"show_id": show_id, "exhibitor_name": "A. Grower", "plant_name": "Entry"},
    )
    entries = [
        _post(
            client,
            "/api/entries",
            {"show_id": show_id, "exhibitor_name": "B. Grower", "plant_name": name},
        )
        for name in ("Entry one", "Entry two")
    ]
    awards = [
        _post(client, "/api/awards", {"entry_id": e["id"], "award_name": "Blue"})
        for e in entries
    ]
    return {
        **show_day,
        "extra_judges": extra_judges,
        "entry": entry,
        "entries": entries,
        "awards": awards,
    }


def _event_path(ctx, suffix=""):
    return f"/api/judging/events/{ctx['event']['id']}{suffix}"


# Each case builds the n-th request (n = 0 before the lock, 1 after it).
MUTATING_ROUTES = {
    "create_event": lambda ctx, n: (
        "POST",
        f"/api/shows/{ctx['show']['id']}/judging/events",
        {"name": f"Extra event {n}"},
    ),
    "patch_event": lambda ctx, n: (
        "PATCH",
        _event_path(ctx),
        {"name": f"Renamed {n}"},
    ),
    "publish_event": lambda ctx, n: ("POST", _event_path(ctx, "/publish"), None),
    "close_event": lambda ctx, n: ("POST", _event_path(ctx, "/close"), None),
    "create_category": lambda ctx, n: (
        "POST",
        _event_path(ctx, "/categories"),
        {"name": f"Class {n}"},
    ),
    "create_plant": lambda ctx, n: (
        "POST",
        _event_path(ctx, "/plants"),
        {
            "exhibitor_id": ctx["plants"][0]["exhibitor_id"],
            "category_id": ctx["cattleya"]["id"],
            "name": f"Late plant {n}",
        },
    ),
    "create_judge": lambda ctx, n: (
        "POST",
        "/api/judges",
        {"show_id": ctx["show"]["id"], "name": f"Late judge {n}"},
    ),
    "create_assignment": lambda ctx, n: (
        "POST",
        _event_path(ctx, "/assignments"),
        {"judge_id": ctx["extra_judges"][n]["id"]},
    ),
    "generate_scorecards": lambda ctx, n: (
        "POST",
        f"/api/admin/judging_events/{ctx['event']['id']}/generate_scorecards",
        None,
    ),
    "legacy_criterion_scores": lambda ctx, n: (
        "POST",
        f"/api/judging/plants/{ctx['plants'][0]['id']}/scores/{ctx['judges'][0]['id']}",
        {"scores": [{"criterion_id": ctx["criteria"][0]["criteria_id"], "value": 10}]},
    ),
    "create_entry": lambda ctx, n: (
        "POST",
        "/api/entries",
        {
            "show_id": ctx["show"]["id"],
            "exhibitor_name": "Late grower",
            "plant_name": f"Late entry {n}",
        },
    ),
    "patch_entry": lambda ctx, n: (
        "PATCH",
        f"/api/entries/{ctx['entries'][0]['id']}",
        {"exhibitor_name": f"Renamed grower {n}"},
    ),
    "delete_entry": lambda ctx, n: (
        "DELETE",
        f"/api/entries/{ctx['entries'][n]['id']}",
        None,
    ),
    "create_award": lambda ctx, n: (
        "POST",
        "/api/awards",
        {"entry_id": ctx["entry"]["id"], "award_name": f"Ribbon {n}"},
    ),
    "patch_award": lambda ctx, n: (
        "PATCH",
        f"/api/awards/{ctx['awards'][0]['id']}",
        {"level": f"level {n}"},
    ),
    "delete_award": lambda ctx, n: (
        "DELETE",
        f"/api/awards/{ctx['awards'][n]['id']}",
        None,
    ),
    "score_submission": lambda ctx, n: (
        "POST",
        "/api/score-submissions",
        {
            "show_id": ctx["show"]["id"],
            "entry_id": ctx["entry"]["id"],
            "judge_id": ctx["judges"][n]["id"],
            "total_points": 80,
        },
    ),
}


@pytest.mark.parametrize("route", sorted(MUTATING_ROUTES))
def test_mutating_judging_route_is_frozen_by_show_lock(client, lock_ctx, route):
    build = MUTATING_ROUTES[route]

    before = _send(client, *build(lock_ctx, 0))
    assert before.status_code == 200, before.text

    _set_lock(client, lock_ctx, True)
    after = _send(client, *build(lock_ctx, 1))
    assert after.status_code == 409, after.text
    assert "locked" in after.json()["detail"].lower()


def test_owner_unlock_through_show_patch_restores_edits(client, lock_ctx):
    method, path, body = MUTATING_ROUTES["create_plant"](lock_ctx, 0)
    _set_lock(client, lock_ctx, True)
    assert _send(client, method, path, body).status_code == 409
    _set_lock(client, lock_ctx, False)
    assert _send(client, method, path, body).status_code == 200


def test_locked_entry_patch_leaves_leaderboard_names_unchanged(client, lock_ctx):
    entry = lock_ctx["entry"]
    _post(
        client,
        "/api/score-submissions",
        {
            "show_id": lock_ctx["show"]["id"],
            "entry_id": entry["id"],
            "judge_id": lock_ctx["judges"][0]["id"],
            "total_points": 80,
        },
    )
    _set_lock(client, lock_ctx, True)
    renamed = _send(
        client, "PATCH", f"/api/entries/{entry['id']}", {"exhibitor_name": "Someone"}
    )
    assert renamed.status_code == 409
    board = client.get(
        f"/api/shows/{lock_ctx['show']['id']}/leaderboard", headers=HEADERS
    ).json()["leaderboard"]
    assert [row["exhibitor_name"] for row in board] == ["A. Grower"]


def test_locked_show_cannot_be_deleted_until_owner_unlocks(client, show_day):
    show_path = f"/api/shows/{show_day['show']['id']}"
    _set_lock(client, show_day, True)
    assert _send(client, "DELETE", show_path).status_code == 409
    assert client.get(show_path, headers=HEADERS).status_code == 200
    _set_lock(client, show_day, False)
    assert _send(client, "DELETE", show_path).status_code == 200
    assert client.get(show_path, headers=HEADERS).status_code == 404


def test_assignment_rejects_judge_from_another_show(client, show_day):
    other = _post(
        client, "/api/shows", {"name": "Autumn Show", "start_date": "2027-10-02"}
    )
    outsider = _post(client, "/api/judges", {"show_id": other["id"], "name": "Judge X"})
    response = _send(
        client,
        "POST",
        _event_path(show_day, "/assignments"),
        {"judge_id": outsider["id"]},
    )
    assert response.status_code == 422, response.text


def test_assignment_rejects_category_from_another_event(client, show_day):
    other_event = _post(
        client,
        f"/api/shows/{show_day['show']['id']}/judging/events",
        {"name": "Trophy judging"},
    )
    foreign_class = _post(
        client, f"/api/judging/events/{other_event['id']}/categories", {"name": "Vanda"}
    )
    judge = _post(
        client, "/api/judges", {"show_id": show_day["show"]["id"], "name": "Judge E"}
    )
    response = _send(
        client,
        "POST",
        _event_path(show_day, "/assignments"),
        {"judge_id": judge["id"], "category_id": foreign_class["id"]},
    )
    assert response.status_code == 422, response.text
    own_class = _send(
        client,
        "POST",
        _event_path(show_day, "/assignments"),
        {"judge_id": judge["id"], "category_id": show_day["cattleya"]["id"]},
    )
    assert own_class.status_code == 200, own_class.text


@pytest.mark.parametrize(
    ("action", "stamp"), [("publish", "published_at"), ("close", "closed_at")]
)
def test_repeated_publish_or_close_keeps_first_timestamp(
    client, show_day, action, stamp
):
    first = _send(client, "POST", _event_path(show_day, f"/{action}"))
    assert first.status_code == 200 and first.json()[stamp] is not None
    again = _send(client, "POST", _event_path(show_day, f"/{action}"))
    assert again.status_code == 200
    assert again.json()[stamp] == first.json()[stamp]


def test_locked_show_rejects_event_status_change(client, show_day):
    _set_lock(client, show_day, True)
    response = _send(client, "PATCH", _event_path(show_day), {"status": "closed"})
    assert response.status_code == 409
    event = client.get(_event_path(show_day), headers=HEADERS).json()
    assert event["status"] == "draft"


@pytest.mark.parametrize("target", ["open", "draft", "published"])
def test_closed_event_cannot_be_reopened_by_patch(client, show_day, target):
    assert _send(client, "POST", _event_path(show_day, "/close")).status_code == 200

    response = _send(client, "PATCH", _event_path(show_day), {"status": target})
    assert response.status_code == 409, response.text
    event = client.get(_event_path(show_day), headers=HEADERS).json()
    assert event["status"] == "closed"


def test_closed_event_accepts_same_status_and_non_status_edits(client, show_day):
    assert _send(client, "POST", _event_path(show_day, "/close")).status_code == 200
    same = _send(client, "PATCH", _event_path(show_day), {"status": "closed"})
    assert same.status_code == 200 and same.json()["status"] == "closed"
    renamed = _send(client, "PATCH", _event_path(show_day), {"name": "Ribbon results"})
    assert renamed.status_code == 200 and renamed.json()["name"] == "Ribbon results"


def test_event_status_patch_moves_forward_only(client, show_day):
    published = _send(client, "PATCH", _event_path(show_day), {"status": "published"})
    assert published.status_code == 200
    assert published.json()["status"] == "published"
    assert published.json()["published_at"] is not None

    back = _send(client, "PATCH", _event_path(show_day), {"status": "draft"})
    assert back.status_code == 409

    unknown = _send(client, "PATCH", _event_path(show_day), {"status": "open"})
    assert unknown.status_code == 422

    closed = _send(client, "PATCH", _event_path(show_day), {"status": "closed"})
    assert closed.status_code == 200
    assert closed.json()["status"] == "closed"
    assert closed.json()["closed_at"] is not None


def _legacy_rows(client, ctx):
    response = client.get(_event_path(ctx, "/results"), headers=HEADERS)
    assert response.status_code == 200, response.text
    return {row["plant_id"]: row for row in response.json()["results"]}


def test_legacy_results_withhold_exhibitor_for_blind_events(client, show_day):
    plant, judge = show_day["plants"][0], show_day["judges"][0]
    _score(client, show_day, plant, judge, 45, 40)

    open_row = _legacy_rows(client, show_day)[plant["id"]]
    assert open_row["exhibitor_name"] == "A. Grower <Esq>"
    assert open_row["avg_weighted_score"] == 85.0

    blind = _send(client, "PATCH", _event_path(show_day), {"is_blind": True})
    assert blind.status_code == 200 and blind.json()["is_blind"] is True
    blind_row = _legacy_rows(client, show_day)[plant["id"]]
    assert "exhibitor_name" in blind_row
    assert blind_row["exhibitor_name"] is None
    assert blind_row["avg_weighted_score"] == 85.0
    assert blind_row["category_name"] == "Cattleya"
