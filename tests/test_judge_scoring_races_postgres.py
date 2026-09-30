"""PostgreSQL proof that judge score writes cannot race the lock or each other.

Skipped unless ``SHOW_JUDGING_TEST_POSTGRES_URL`` names a disposable
PostgreSQL database (psycopg2 required). Each test works in a fresh schema
that it drops afterwards. All rows are labelled synthetic test shapes.

A holder session takes the lock a concurrent owner action (or a concurrent
submit) would hold; the scoring helper, run in a thread, must wait for it and
then see its committed effect. Without the row locks in
``app/routers/judging.py::_lock_scoring_rows`` the helper does not wait and
both writes succeed.
"""

import os
import re
import secrets
import threading
from datetime import date
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import (
    Exhibitor,
    Judge,
    JudgeActionAudit,
    JudgingEvent,
    Plant,
    PlantCategory,
    Scorecard,
    Show,
)
from app.routers.judging import apply_scorecard_autosave, apply_scorecard_submit
from app.schemas import ScorecardSaveRequest, ScorecardSubmitRequest
from app.show_app import SHOW_TABLES

URL = os.environ.get("SHOW_JUDGING_TEST_POSTGRES_URL", "")
try:
    import psycopg2  # noqa: F401

    _HAS_PSYCOPG2 = True
except ImportError:
    _HAS_PSYCOPG2 = False

pytestmark = pytest.mark.skipif(
    not (URL.startswith("postgresql") and _HAS_PSYCOPG2),
    reason="set SHOW_JUDGING_TEST_POSTGRES_URL to a disposable PostgreSQL database",
)

MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "20260930_show_judge_credentials.sql"
)
BLOCK_SECONDS = 0.8


@pytest.fixture
def pg():
    schema = f"g8race_{secrets.token_hex(4)}"
    admin = create_engine(URL)
    with admin.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_engine(URL, connect_args={"options": f"-csearch_path={schema}"})
    try:
        Base.metadata.create_all(engine, tables=list(SHOW_TABLES))
        yield engine, sessionmaker(bind=engine, expire_on_commit=False)
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()


@pytest.fixture
def card(pg):
    _engine, factory = pg
    with factory() as db:
        show = Show(name="Race Show", start_date=date(2027, 3, 13))
        db.add(show)
        db.flush()
        event = JudgingEvent(show_id=show.id, name="Race judging")
        db.add(event)
        db.flush()
        category = PlantCategory(judging_event_id=event.id, name="Cattleya")
        exhibitor = Exhibitor(name="Synthetic Exhibitor")
        judge = Judge(show_id=show.id, name="Judge A")
        db.add_all([category, exhibitor, judge])
        db.flush()
        plant = Plant(
            exhibitor_id=exhibitor.id,
            judging_event_id=event.id,
            category_id=category.id,
            name="Cattleya trianae",
        )
        db.add(plant)
        db.flush()
        scorecard = Scorecard(
            judging_event_id=event.id, plant_id=plant.id, judge_id=judge.id
        )
        db.add(scorecard)
        db.commit()
        return {"show_id": show.id, "card_id": scorecard.id, "judge_id": judge.id}


def _run(factory, ids, action):
    outcome = {}

    def worker():
        with factory() as db:
            scorecard = db.get(Scorecard, ids["card_id"])
            try:
                if action == "submit":
                    apply_scorecard_submit(
                        db, scorecard, ids["judge_id"], ScorecardSubmitRequest()
                    )
                else:
                    apply_scorecard_autosave(
                        db, scorecard, ids["judge_id"], ScorecardSaveRequest(scores=[])
                    )
                outcome["status"] = 200
            except HTTPException as exc:
                outcome["status"] = exc.status_code
                outcome["detail"] = exc.detail

    thread = threading.Thread(target=worker)
    thread.start()
    return thread, outcome


def test_second_submit_waits_for_the_first_and_is_refused(pg, card):
    _engine, factory = pg
    with factory() as holder:
        held = holder.execute(
            select(Scorecard).where(Scorecard.id == card["card_id"]).with_for_update()
        ).scalar_one()
        thread, outcome = _run(factory, card, "submit")
        thread.join(BLOCK_SECONDS)
        assert thread.is_alive(), "submit did not wait for the scorecard row lock"
        held.status = "submitted"
        holder.commit()
    thread.join(10)
    assert outcome["status"] == 409


@pytest.mark.parametrize("action", ["submit", "autosave"])
def test_score_write_waits_for_a_concurrent_lock_and_then_honours_it(pg, card, action):
    _engine, factory = pg
    with factory() as holder:
        holder.execute(
            text("UPDATE shows SET judging_locked = true WHERE id = :id"),
            {"id": card["show_id"]},
        )
        thread, outcome = _run(factory, card, action)
        thread.join(BLOCK_SECONDS)
        assert thread.is_alive(), f"{action} did not wait for the show row"
        holder.commit()
    thread.join(10)
    assert outcome["status"] == 409 and "locked" in outcome["detail"].lower()
    with factory() as db:
        assert db.get(Scorecard, card["card_id"]).status == "draft"


@pytest.mark.parametrize("action", ["submit", "autosave"])
def test_score_write_waits_for_a_concurrent_event_close_and_then_honours_it(
    pg, card, action
):
    _engine, factory = pg
    with factory() as holder:
        holder.execute(
            text(
                "UPDATE judging_events SET status = 'closed' "
                "WHERE id = (SELECT judging_event_id FROM scorecards WHERE id = :id)"
            ),
            {"id": card["card_id"]},
        )
        thread, outcome = _run(factory, card, action)
        thread.join(BLOCK_SECONDS)
        assert thread.is_alive(), f"{action} did not wait for the event row"
        holder.commit()
    thread.join(10)
    assert outcome["status"] == 409 and "closed" in outcome["detail"].lower()
    with factory() as db:
        assert db.get(Scorecard, card["card_id"]).status == "draft"


def test_concurrent_submits_yield_exactly_one_success(pg, card):
    _engine, factory = pg
    runs = [_run(factory, card, "submit") for _ in range(2)]
    for thread, _ in runs:
        thread.join(10)
    assert sorted(outcome["status"] for _, outcome in runs) == [200, 409]
    with factory() as db:
        assert db.get(Scorecard, card["card_id"]).status == "submitted"


def test_audit_table_refuses_update_delete_and_truncate(pg):
    engine, factory = pg
    with factory() as db:
        db.add(
            JudgeActionAudit(
                judge_id="synthetic", action="me", outcome="ok", http_status=200
            )
        )
        db.commit()
    for statement in (
        "UPDATE judge_action_audit SET outcome = 'x'",
        "DELETE FROM judge_action_audit",
        "TRUNCATE judge_action_audit",
    ):
        with pytest.raises(Exception, match="append-only"), engine.begin() as conn:
            conn.execute(text(statement))
    with factory() as db:
        assert len(db.execute(select(JudgeActionAudit)).scalars().all()) == 1


def test_migration_reapplies_cleanly_over_a_create_all_schema(pg):
    engine, _factory = pg
    sql = MIGRATION.read_text(encoding="utf-8")
    for _ in range(2):
        raw = engine.raw_connection()
        try:
            with raw.cursor() as cursor:
                cursor.execute(sql)
            raw.commit()
        finally:
            raw.close()
    with engine.connect() as conn:
        triggers = conn.execute(
            text(
                "SELECT tgname FROM pg_trigger "
                "WHERE tgrelid = 'judge_action_audit'::regclass AND NOT tgisinternal"
            )
        ).scalars()
        assert sorted(triggers) == [
            "judge_action_audit_no_truncate",
            "judge_action_audit_no_update_delete",
        ]
    assert re.search(r"BEFORE TRUNCATE", sql)
