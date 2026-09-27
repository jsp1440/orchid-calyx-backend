"""#1652 — the public newsletter/contact API over the canonical oc_constituent / oc_communications schemas.

Re-runnable against a persistent database: every test works in its own
platform-kind organization (unique slug) with unique addresses, and never
assumes empty tables.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import psycopg
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from app import rate_limit
from app.constituent_platform import canonical_store as cs
from app.constituent_platform import routes as constituent_routes
from app.constituent_platform import service as legacy
from app.constituent_platform.domain import (
    AudienceMember,
    CommunicationState,
    MessagePurpose,
    PreferenceState,
    audience_snapshot_sha256,
)
from app.constituent_platform.research_station_migration import migrate
from app.constituent_platform.tenant_db import dsn_connection_factory, tenant_transaction
from app.routers.health import add_mission_control_cors_headers
from app.security import verify_owner_or_api_key
from runtime.research_station_store import MemoryProjectRecordStore, PostgresProjectRecordStore

pytestmark = pytest.mark.requires_postgres("DATABASE_URL", psql=False)

MIGRATIONS = [
    "migrations/20260823_oc_constituent_communications_foundation.sql",
    "migrations/20260926_society_crm_p0_core.sql",
    "migrations/20260927_society_crm_p1_tenant_isolation.sql",
    "migrations/20260927b_constituent_newsletter_canonical.sql",
    "migrations/20260927b_constituent_newsletter_canonical.sql",  # idempotency
]
OWNER_AUTH = {"actor": "owner", "auth_type": "owner_session"}


def _dsn() -> str:
    return cs.normalized_dsn(os.environ["DATABASE_URL"])


def _apply_migrations(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        for path in MIGRATIONS:
            conn.execute(Path(path).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def dsn() -> str:
    value = _dsn()
    _apply_migrations(value)
    return value


def _slug() -> str:
    return f"oc-newsletter-test-{uuid.uuid4().hex[:12]}"


def _email(label: str = "reader") -> str:
    return f"{label}-{uuid.uuid4().hex[:10]}@example.com"


@pytest.fixture()
def service(dsn) -> cs.CanonicalConstituentService:
    svc = cs.CanonicalConstituentService(connect=dsn_connection_factory(dsn), organization_slug=_slug())
    svc.ensure_ready()
    return svc


def _admin(dsn: str):
    return psycopg.connect(dsn, row_factory=dict_row, autocommit=True)


def _org(svc: cs.CanonicalConstituentService) -> int:
    return svc.ensure_ready()


def _constituent_id(dsn: str, org: int, email: str) -> int:
    with _admin(dsn) as conn:
        row = conn.execute(
            """
            SELECT constituent_id FROM oc_communications.newsletter_subscription_settings
            WHERE organization_id = %s AND public_constituent_id = %s
            """,
            (org, legacy.constituent_id_for(email)),
        ).fetchone()
    return int(row["constituent_id"])


def _ledger(dsn: str, org: int, constituent_id: int) -> list[dict]:
    with _admin(dsn) as conn:
        return conn.execute(
            """
            SELECT id, state, supersedes_id, channel, purpose, topic FROM oc_constituent.communication_preferences
            WHERE organization_id = %s AND constituent_id = %s ORDER BY id
            """,
            (org, constituent_id),
        ).fetchall()


def _suppressions(dsn: str, org: int, constituent_id: int) -> list[dict]:
    with _admin(dsn) as conn:
        return conn.execute(
            """
            SELECT kind, lifted_at FROM oc_constituent.suppressions
            WHERE organization_id = %s AND constituent_id = %s ORDER BY id
            """,
            (org, constituent_id),
        ).fetchall()


# -- ledger and suppressions ------------------------------------------------------------------


def test_platform_organization_is_orchid_continuum_kind(dsn, service):
    with _admin(dsn) as conn:
        row = conn.execute(
            "SELECT kind, status FROM oc_constituent.organizations WHERE id = %s", (_org(service),)
        ).fetchone()
    assert row == {"kind": "orchid_continuum", "status": "active"}


def test_subscribe_unsubscribe_resubscribe_appends_ledger_and_lifts_only_own_unsubscribe(dsn, service):
    email = _email()
    org = _org(service)
    first = service.subscribe(email, display_name="A Reader", topics=["shows", "orchid-news", "shows"], frequency="weekly", format="html")
    record = first["subscription"]
    assert record["constituent_id"] == legacy.constituent_id_for(email)
    assert record["state"] == PreferenceState.SUBSCRIBED.value
    assert record["topics"] == ["orchid-news", "shows"]
    assert record["suppressions"] == []
    cid = _constituent_id(dsn, org, email)
    ledger = _ledger(dsn, org, cid)
    assert [(row["state"], row["channel"], row["purpose"], row["topic"]) for row in ledger] == [
        ("subscribed", "email", "community", "*")
    ]

    out = service.unsubscribe(email, reason="too many emails")
    assert out["state"] == PreferenceState.UNSUBSCRIBED.value
    assert out["suppressions"] == ["unsubscribe"]
    again = service.unsubscribe(email, reason=None)  # idempotent
    assert again["state"] == PreferenceState.UNSUBSCRIBED.value
    ledger = _ledger(dsn, org, cid)
    assert [row["state"] for row in ledger] == ["subscribed", "unsubscribed"]
    assert ledger[1]["supersedes_id"] == ledger[0]["id"]
    assert [(row["kind"], row["lifted_at"]) for row in _suppressions(dsn, org, cid)] == [("unsubscribe", None)]

    back = service.subscribe(email, display_name=None, topics=["shows"], frequency="monthly", format="plain")
    record = back["subscription"]
    assert record["state"] == PreferenceState.SUBSCRIBED.value
    assert record["suppressions"] == []
    assert record["display_name"] == "A Reader"
    assert (record["topics"], record["frequency"], record["format"]) == (["shows"], "monthly", "plain")
    ledger = _ledger(dsn, org, cid)
    assert [row["state"] for row in ledger] == ["subscribed", "unsubscribed", "subscribed"]
    assert ledger[2]["supersedes_id"] == ledger[1]["id"]
    suppressions = _suppressions(dsn, org, cid)
    assert len(suppressions) == 1 and suppressions[0]["lifted_at"] is not None
    assert [item["event"] for item in record["history"]] == ["subscribed", "unsubscribed", "subscribed"]


@pytest.mark.parametrize("critical", ["hard_bounce", "complaint", "invalid", "admin_block"])
def test_critical_suppression_survives_resubscribe_and_denies_community_mail(dsn, service, critical):
    email = _email()
    org = _org(service)
    service.subscribe(email, display_name=None, topics=[], frequency="weekly", format="html")
    cid = _constituent_id(dsn, org, email)
    with _admin(dsn) as conn:
        conn.execute(
            """
            INSERT INTO oc_constituent.suppressions (organization_id, constituent_id, normalized_email, kind, source_kind)
            VALUES (%s, %s, %s, %s, 'delivery_provider')
            """,
            (org, cid, email, critical),
        )
    service.unsubscribe(email, reason=None)
    record = service.subscribe(email, display_name=None, topics=["shows"], frequency="weekly", format="html")["subscription"]
    assert record["state"] == PreferenceState.SUBSCRIBED.value
    assert record["suppressions"] == [critical]
    kinds = {row["kind"]: row["lifted_at"] for row in _suppressions(dsn, org, cid)}
    assert kinds[critical] is None
    assert kinds["unsubscribe"] is not None
    assert service.delivery_decision(email, MessagePurpose.COMMUNITY) == (False, "critical_suppression")


def test_unsubscribe_answers_identically_for_unknown_addresses(service):
    known = _email("known")
    unknown = _email("unknown")
    service.subscribe(known, display_name=None, topics=[], frequency="weekly", format="html")
    a = service.unsubscribe(known, reason=None)
    b = service.unsubscribe(unknown, reason=None)
    assert set(a) == set(b)
    assert a["state"] == b["state"] == PreferenceState.UNSUBSCRIBED.value
    assert a["suppressions"] == b["suppressions"] == ["unsubscribe"]
    assert service.delivery_decision(unknown, MessagePurpose.COMMUNITY) == (False, "unsubscribed")
    assert service.get_subscription(_email("never")) is None


def test_update_preferences_changes_settings_not_state(service):
    email = _email()
    with pytest.raises(legacy.NotFound):
        service.update_preferences(email, topics=["shows"], frequency=None, format=None)
    service.subscribe(email, display_name=None, topics=["shows"], frequency="weekly", format="html")
    updated = service.update_preferences(email, topics=["fundraising", "shows"], frequency="monthly", format=None)
    assert (updated["topics"], updated["frequency"], updated["format"]) == (["fundraising", "shows"], "monthly", "html")
    assert updated["state"] == PreferenceState.SUBSCRIBED.value
    cleared = service.update_preferences(email, topics=[], frequency=None, format="plain")
    assert (cleared["topics"], cleared["frequency"], cleared["format"]) == ([], "monthly", "plain")


# -- welcome intent -----------------------------------------------------------------------------


def test_welcome_intent_is_frozen_awaiting_approval_and_idempotent(dsn, service):
    email = _email()
    org = _org(service)
    result = service.subscribe(email, display_name=None, topics=[], frequency="weekly", format="html")
    communication = result["communication"]
    public_id = legacy.constituent_id_for(email)
    assert communication == {
        "communication_id": f"welcome-{public_id}",
        "purpose": "community",
        "state": CommunicationState.AWAITING_APPROVAL.value,
        "approval_required": True,
        "audience_size": 1,
        "constituent_id": public_id,
        "requested_at": communication["requested_at"],
        "dispatch": "blocked_pending_human_approval",
    }
    cid = _constituent_id(dsn, org, email)
    service.unsubscribe(email, reason=None)
    again = service.subscribe(email, display_name=None, topics=["shows"], frequency="weekly", format="html")
    assert again["communication"] == communication

    with _admin(dsn) as conn:
        intents = conn.execute(
            """
            SELECT i.id, i.state, i.purpose, s.id AS snapshot_id, s.audience_sha256, s.frozen_at, s.organization_id AS snap_org
            FROM oc_communications.intents i
            JOIN oc_communications.audience_snapshots s ON s.intent_id = i.id
            WHERE i.organization_id = %s AND i.initiating_module = 'constituent_platform.welcome'
              AND i.audience_definition ->> 'constituent_id' = %s
            """,
            (org, str(cid)),
        ).fetchall()
        assert len(intents) == 1
        intent = intents[0]
        assert intent["state"] == "awaiting_approval" and intent["purpose"] == "community"
        assert intent["frozen_at"] is not None and intent["snap_org"] == org
        members = conn.execute(
            "SELECT constituent_id, normalized_email, allowed, decision_reason, organization_id "
            "FROM oc_communications.audience_members WHERE snapshot_id = %s",
            (intent["snapshot_id"],),
        ).fetchall()
        assert members == [
            {"constituent_id": cid, "normalized_email": email, "allowed": True, "decision_reason": "subscribed", "organization_id": org}
        ]
        expected = audience_snapshot_sha256([AudienceMember(cid, email, True, "subscribed")])
        assert intent["audience_sha256"] == expected
        with pytest.raises(psycopg.errors.RaiseException, match="FROZEN_AUDIENCE_IMMUTABLE"):
            conn.execute(
                "INSERT INTO oc_communications.audience_members "
                "(organization_id, snapshot_id, constituent_id, normalized_email, allowed, decision_reason) "
                "VALUES (%s, %s, %s, %s, TRUE, 'subscribed')",
                (org, intent["snapshot_id"], cid, _email("intruder")),
            )


# -- archive and contact --------------------------------------------------------------------------


def _issue(published_at: str, title: str = "Issue") -> dict:
    return {
        "newsletter_id": str(uuid.uuid4()),
        "title": title,
        "published_at": published_at,
        "topic_slugs": ["orchid-news"],
        "html_body": "<p>Notes.</p>",
        "plain_text_body": "Notes.",
        "purpose": "community",
    }


def test_newsletter_archive_publishes_lists_newest_first_and_is_idempotent(service):
    older = service.publish_issue(_issue("2026-08-01T12:00:00+00:00", "August"))
    newer = service.publish_issue(_issue("2026-09-01T12:00:00+00:00", "September"))
    assert older["state"] == "completed" and older["published_at"] == "2026-08-01T12:00:00+00:00"
    assert [row["title"] for row in service.list_issues()] == ["September", "August"]
    assert service.get_issue(newer["newsletter_id"])["html_body"] == "<p>Notes.</p>"
    replay = service.publish_issue({**_issue("2026-09-01T12:00:00+00:00", "Replayed"), "newsletter_id": newer["newsletter_id"]})
    assert replay["title"] == "September"
    assert len(service.list_issues()) == 2
    with pytest.raises(legacy.NotFound):
        service.get_issue(str(uuid.uuid4()))
    with pytest.raises(legacy.NotFound):
        service.get_issue("not-a-uuid")


def test_contact_messages_are_idempotent_untrusted_and_paginated(service):
    email = _email("grower")
    message = {"category": "bug", "name": "A. Grower", "normalized_email": email, "subject": "Map", "body": "The map is blank on iPad.", "source": "contact-page"}
    first = service.receive_contact(message)
    second = service.receive_contact(dict(message))
    assert first == second
    assert first["reference_id"] == legacy.contact_reference_id(message)
    assert (first["review"], first["agent_exposure"], first["content_trust"]) == (
        "human_review_required",
        "never_forwarded_to_agents",
        "untrusted_plain_text",
    )
    service.receive_contact({**message, "body": "A second, different message body."})
    rows, total = service.list_contact_messages(limit=1, offset=0)
    assert total == 2 and len(rows) == 1
    rows, _ = service.list_contact_messages(limit=10, offset=1)
    assert len(rows) == 1


# -- tenant isolation -------------------------------------------------------------------------------


def test_rows_are_invisible_and_unwritable_under_another_tenant(dsn, service):
    other = cs.CanonicalConstituentService(connect=dsn_connection_factory(dsn), organization_slug=_slug())
    org_a, org_b = _org(service), other.ensure_ready()
    email = _email()
    service.subscribe(email, display_name=None, topics=[], frequency="weekly", format="html")
    service.publish_issue(_issue("2026-09-01T00:00:00+00:00"))
    service.receive_contact({"category": "general", "name": None, "normalized_email": email, "subject": None, "body": "Hello from tenant A.", "source": None})

    connect = dsn_connection_factory(dsn)
    tables = [
        "oc_communications.newsletter_subscription_settings",
        "oc_communications.newsletter_issues",
        "oc_communications.inbound_contact_messages",
        "oc_communications.intents",
        "oc_communications.audience_snapshots",
        "oc_communications.audience_members",
        "oc_constituent.communication_preferences",
        "oc_constituent.email_addresses",
    ]
    with tenant_transaction(org_b, connect=connect) as cur:
        for table in tables:
            cur.execute(f"SELECT count(*) AS n FROM {table} WHERE organization_id = %s", (org_a,))
            assert cur.fetchone()["n"] == 0, table
    with tenant_transaction(org_a, connect=connect) as cur:
        for table in tables:
            cur.execute(f"SELECT count(*) AS n FROM {table} WHERE organization_id = %s", (org_a,))
            assert cur.fetchone()["n"] >= 1, table
    assert other.get_subscription(email) is None
    assert other.subscription_summary()["total"] == 0
    assert other.list_issues() == []

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with tenant_transaction(org_b, connect=connect) as cur:
            cur.execute(
                "INSERT INTO oc_communications.newsletter_issues "
                "(organization_id, newsletter_id, title, published_at, html_body, plain_text_body, content_sha256) "
                "VALUES (%s, %s, 'x', NOW(), 'x', 'x', repeat('0', 64))",
                (org_a, str(uuid.uuid4())),
            )
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with tenant_transaction(org_a, connect=connect) as cur:
            cur.execute("DELETE FROM oc_communications.inbound_contact_messages WHERE organization_id = %s", (org_a,))


# -- migration tool -----------------------------------------------------------------------------------


def _legacy_store(emails: list[str]) -> MemoryProjectRecordStore:
    store = MemoryProjectRecordStore()
    old = legacy.ConstituentService(store)
    old.subscribe(emails[0], display_name="Reader One", topics=["shows"], frequency="weekly", format="html")
    old.subscribe(emails[1], display_name=None, topics=[], frequency="monthly", format="plain")
    old.unsubscribe(emails[1], reason="moving")
    old.publish_issue(_issue("2026-07-01T00:00:00+00:00", "July"))
    old.receive_contact({"category": "general", "name": None, "normalized_email": emails[0], "subject": None, "body": "Legacy contact body.", "source": None})
    return store


def _counts(report: dict) -> dict:
    return {key: value for key, value in report["counts"].items() if value}


def test_migration_dry_run_apply_rerun_conflict_and_invalid(dsn):
    slug = _slug()
    connect = dsn_connection_factory(dsn)
    emails = [_email("legacy-a"), _email("legacy-b")]
    store = _legacy_store(emails)
    store.put(
        owner_key=legacy.OWNER_KEY,
        project_id=legacy.PROJECT_SUBSCRIPTIONS,
        kind=legacy.KIND_SUBSCRIPTION,
        record_id="bad-row",
        record={"normalized_email": "not-an-email", "state": "subscribed", "constituent_id": "x"},
    )

    dry = migrate(store, connect=connect, organization_slug=slug)
    assert dry["mode"] == "dry_run" and dry["writes_performed"] is False
    assert _counts(dry) == {"created": 6, "invalid": 1}  # 2 subscriptions, 2 welcomes, 1 issue, 1 contact
    invalid = [entry for entry in dry["records"] if entry["outcome"] == "invalid"]
    assert invalid[0]["kind"] == "subscription" and invalid[0]["reason"] == "invalid_email"
    assert "@" not in json.dumps(dry)
    with _admin(dsn) as conn:
        assert conn.execute("SELECT 1 FROM oc_constituent.organizations WHERE slug = %s", (slug,)).fetchone() is None

    applied = migrate(store, connect=connect, organization_slug=slug, apply=True)
    assert _counts(applied) == {"created": 6, "invalid": 1}
    assert applied["writes_performed"] is True
    canonical = cs.CanonicalConstituentService(connect=connect, organization_slug=slug)
    a = canonical.get_subscription(emails[0])
    b = canonical.get_subscription(emails[1])
    assert (a["state"], a["topics"], a["display_name"]) == ("subscribed", ["shows"], "Reader One")
    assert (b["state"], b["suppressions"], b["frequency"], b["format"]) == ("unsubscribed", ["unsubscribe"], "monthly", "plain")
    assert canonical.subscription_summary() == {
        "total": 2,
        "by_state": {"subscribed": 1, "unsubscribed": 1},
        "welcome_communications_awaiting_approval": 2,
    }
    assert [row["title"] for row in canonical.list_issues()] == ["July"]
    assert canonical.list_contact_messages(limit=10, offset=0)[1] == 1

    rerun = migrate(store, connect=connect, organization_slug=slug, apply=True)
    assert _counts(rerun) == {"unchanged": 6, "invalid": 1}
    assert rerun["writes_performed"] is False and rerun["cutover_ready"] is False

    # New legacy record + dry run against an existing org: planned, not written.
    legacy.ConstituentService(store).receive_contact(
        {"category": "bug", "name": None, "normalized_email": emails[1], "subject": None, "body": "Arrived after apply.", "source": None}
    )
    planned = migrate(store, connect=connect, organization_slug=slug)
    assert _counts(planned) == {"created": 1, "unchanged": 6, "invalid": 1}
    assert canonical.list_contact_messages(limit=10, offset=0)[1] == 1

    # Divergent canonical state is a conflict, never overwritten.
    record = store.get(
        owner_key=legacy.OWNER_KEY,
        project_id=legacy.PROJECT_SUBSCRIPTIONS,
        kind=legacy.KIND_SUBSCRIPTION,
        record_id=legacy.subscription_record_id(emails[0]),
    )
    store.put(
        owner_key=legacy.OWNER_KEY,
        project_id=legacy.PROJECT_SUBSCRIPTIONS,
        kind=legacy.KIND_SUBSCRIPTION,
        record_id=legacy.subscription_record_id(emails[0]),
        record={**record, "topics": ["cultivation"], "state": "unsubscribed", "suppressions": ["unsubscribe"]},
    )
    conflicted = migrate(store, connect=connect, organization_slug=slug, apply=True)
    conflicts = [entry for entry in conflicted["records"] if entry["outcome"] == "conflict"]
    assert len(conflicts) == 1
    assert conflicts[0]["fields"] == ["state", "suppressions", "topics"]
    assert conflicts[0]["record_id"] == legacy.subscription_record_id(emails[0])
    after = canonical.get_subscription(emails[0])
    assert (after["state"], after["topics"]) == ("subscribed", ["shows"])


def test_migration_of_a_clean_store_reaches_cutover_ready(dsn):
    slug = _slug()
    connect = dsn_connection_factory(dsn)
    store = _legacy_store([_email("clean-a"), _email("clean-b")])
    migrate(store, connect=connect, organization_slug=slug, apply=True)
    verify = migrate(store, connect=connect, organization_slug=slug)
    assert verify["cutover_ready"] is True
    assert _counts(verify) == {"unchanged": 6}


def test_migration_reports_orphan_welcome_as_invalid(dsn):
    store = MemoryProjectRecordStore()
    orphan = legacy.constituent_id_for(_email("orphan"))
    store.put(
        owner_key=legacy.OWNER_KEY,
        project_id=legacy.PROJECT_WELCOME,
        kind=legacy.KIND_COMMUNICATION,
        record_id=orphan,
        record={"constituent_id": orphan, "state": "awaiting_approval", "requested_at": "2026-09-01T00:00:00+00:00"},
    )
    report = migrate(store, connect=dsn_connection_factory(dsn), organization_slug=_slug(), apply=True)
    assert report["records"] == [
        {"kind": "welcome_communication", "record_id": orphan, "outcome": "invalid", "reason": "orphan_welcome_communication"}
    ]


def test_migration_script_dry_run_reads_research_station_table_and_writes_nothing(dsn, tmp_path, capsys):
    from scripts.oc_constituent_migrate_research_station import main

    with _admin(dsn) as conn:
        conn.execute(Path("migrations/CALYX-RECOVERY-001-research-station-records.sql").read_text(encoding="utf-8"))
    source = PostgresProjectRecordStore(lambda work: _run(dsn, work))
    newsletter_id = str(uuid.uuid4())
    record = {**_issue("2026-06-01T00:00:00+00:00", "June"), "newsletter_id": newsletter_id, "state": "completed"}
    source.put(owner_key=legacy.OWNER_KEY, project_id=legacy.PROJECT_ARCHIVE, kind=legacy.KIND_ISSUE, record_id=newsletter_id, record=record)
    slug = _slug()
    report_path = tmp_path / "report.json"
    try:
        code = main(["--organization-slug", slug, "--report", str(report_path), "--database-url", dsn])
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert code in (0, 2)
        assert report["mode"] == "dry_run"
        mine = [entry for entry in report["records"] if entry["record_id"] == newsletter_id]
        assert mine == [{"kind": "newsletter_issue", "record_id": newsletter_id, "outcome": "created"}]
        with _admin(dsn) as conn:
            assert conn.execute("SELECT 1 FROM oc_constituent.organizations WHERE slug = %s", (slug,)).fetchone() is None
        assert json.loads(capsys.readouterr().out)["counts"] == report["counts"]
    finally:
        with _admin(dsn) as conn:
            conn.execute(
                "DELETE FROM oc_admin.research_station_records WHERE owner_key = %s AND record_id = %s",
                (legacy.OWNER_KEY, newsletter_id),
            )


def _run(dsn: str, work):
    with psycopg.connect(dsn, row_factory=dict_row) as conn, conn.cursor() as cur:
        return work(cur)


# -- routes over the canonical store --------------------------------------------------------------------


@pytest.fixture()
def canonical_routes(monkeypatch, service):
    monkeypatch.setenv(cs.PERSISTENCE_ENV, "canonical")
    for name in ("CALYX_API_KEY", "CONSTITUENT_MANAGE_SECRET", "CALYX_OWNER_SESSION_SECRET", "PUBLIC_WRITE_RATE_LIMIT"):
        monkeypatch.delenv(name, raising=False)
    rate_limit.LIMITER.reset()
    memory = legacy.memory_store()
    legacy.configure_store(memory)
    cs.configure_canonical_service(service)

    def client(owner: bool) -> TestClient:
        app = FastAPI()
        app.include_router(constituent_routes.router)
        app.include_router(constituent_routes.owner_router)
        app.dependency_overrides[add_mission_control_cors_headers] = lambda: None
        if owner:
            app.dependency_overrides[verify_owner_or_api_key] = lambda: dict(OWNER_AUTH)
            app.dependency_overrides[constituent_routes.owner_if_credentialed] = lambda: dict(OWNER_AUTH)
        return TestClient(app)

    yield client(False), client(True), memory
    cs.configure_canonical_service(None)
    legacy.configure_store(None)


def test_routes_serve_the_public_journeys_from_the_canonical_store(canonical_routes, monkeypatch):
    public, owner, memory = canonical_routes
    a, b, unknown = _email("route-a"), _email("route-b"), _email("route-unknown")

    resp = public.post("/api/constituent/subscribe", json={"email": a.upper(), "topics": ["orchid-news"]})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["constituent_id"] == legacy.constituent_id_for(a)
    assert body["state"] == "subscribed"
    assert body["welcome_email_communication_state"] == "awaiting_approval"
    public.post("/api/constituent/subscribe", json={"email": b})

    known = public.post("/api/constituent/unsubscribe", json={"email": b})
    stranger = public.post("/api/constituent/unsubscribe", json={"email": unknown})
    assert known.status_code == stranger.status_code == 200
    assert {**known.json(), "normalized_email": None} == {**stranger.json(), "normalized_email": None}

    assert public.get("/api/constituent/preferences", params={"email": a}).status_code == 401
    monkeypatch.setenv("CONSTITUENT_MANAGE_SECRET", "test-secret")
    token = public.post("/api/constituent/subscribe", json={"email": a, "topics": ["shows"]}).json()["manage_token"]
    read = public.get("/api/constituent/preferences", params={"email": a, "token": token})
    assert read.status_code == 200, read.text
    assert read.json()["topics"] == ["shows"]
    patched = public.patch("/api/constituent/preferences", params={"email": a, "token": token}, json={"frequency": "monthly"})
    assert patched.status_code == 200 and patched.json()["frequency"] == "monthly"
    assert owner.get("/api/constituent/preferences", params={"email": _email("absent")}).status_code == 404

    issue = {"title": "Canonical issue", "published_at": "2026-09-01T12:00:00Z", "topic_slugs": ["shows"], "html_body": "<p>x</p>", "plain_text_body": "x"}
    assert public.post("/api/constituent/newsletter/archive", json=issue).status_code == 401
    published = owner.post("/api/constituent/newsletter/archive", json=issue)
    assert published.status_code == 201, published.text
    newsletter_id = published.json()["newsletter_id"]
    listing = public.get("/api/constituent/newsletter/archive").json()
    assert listing["total"] == 1 and listing["items"][0]["newsletter_id"] == newsletter_id
    assert public.get(f"/api/constituent/newsletter/archive/{newsletter_id}/web").json()["html_body"] == "<p>x</p>"
    assert public.get(f"/api/constituent/newsletter/archive/{uuid.uuid4()}/web").status_code == 404

    contact = {"category": "bug", "email": a, "body": "The canonical inbox received this.", "subject": "Hi"}
    first = public.post("/api/constituent/contact", json=contact).json()
    assert public.post("/api/constituent/contact", json=contact).json()["reference_id"] == first["reference_id"]
    inbox = owner.get("/api/constituent/contact/messages").json()
    assert inbox["total"] == 1 and inbox["items"][0]["content_trust"] == "untrusted_plain_text"

    summary = owner.get("/api/constituent/subscriptions/summary")
    assert summary.json() == {
        "total": 3,
        "by_state": {"subscribed": 1, "unsubscribed": 2},
        "welcome_communications_awaiting_approval": 2,
    }
    assert "example.com" not in summary.text

    # Nothing leaked into the other store: exactly one store is authoritative.
    for project, kind in [
        (legacy.PROJECT_SUBSCRIPTIONS, legacy.KIND_SUBSCRIPTION),
        (legacy.PROJECT_WELCOME, legacy.KIND_COMMUNICATION),
        (legacy.PROJECT_ARCHIVE, legacy.KIND_ISSUE),
        (legacy.PROJECT_INBOX, legacy.KIND_CONTACT),
    ]:
        assert memory.list(owner_key=legacy.OWNER_KEY, project_id=project, kind=kind) == []


def test_get_service_builds_the_platform_service_from_database_url(monkeypatch, dsn):
    monkeypatch.setenv(cs.PERSISTENCE_ENV, "canonical")
    monkeypatch.setenv("DATABASE_URL", dsn)
    cs.configure_canonical_service(None)
    try:
        svc = constituent_routes.get_service()
        assert isinstance(svc, cs.CanonicalConstituentService)
        assert svc.organization_slug == cs.PLATFORM_ORG_SLUG
        assert constituent_routes.get_service() is svc
    finally:
        cs.configure_canonical_service(None)


def test_unmigrated_database_fails_closed_with_the_migration_named(monkeypatch, dsn):
    name = f"oc_newsletter_unmigrated_{uuid.uuid4().hex[:10]}"
    try:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(f'CREATE DATABASE "{name}"')
    except psycopg.errors.InsufficientPrivilege:
        pytest.skip("test role cannot CREATE DATABASE")
    empty = psycopg.conninfo.make_conninfo(dsn, dbname=name)
    try:
        monkeypatch.setenv(cs.PERSISTENCE_ENV, "canonical")
        monkeypatch.setenv("DATABASE_URL", empty)
        cs.configure_canonical_service(None)
        with pytest.raises(HTTPException) as info:
            constituent_routes.get_service()
        assert info.value.status_code == 503
        assert "20260927b_constituent_newsletter_canonical.sql" in info.value.detail
    finally:
        cs.configure_canonical_service(None)
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}"')
