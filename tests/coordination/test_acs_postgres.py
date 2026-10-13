"""Real PostgreSQL contract; accepts only an explicitly configured local test host."""

import concurrent.futures
import os
import unittest
from urllib.parse import urlsplit

from coordination.store import Principal, Store


@unittest.skipUnless(
    os.environ.get("ACS_TEST_POSTGRES_URL"), "local PostgreSQL test URL unavailable"
)
class PostgreSQLTests(unittest.TestCase):
    def setUp(self):
        self.url = os.environ["ACS_TEST_POSTGRES_URL"]
        parsed = urlsplit(self.url)
        if (
            parsed.hostname not in {"localhost", "127.0.0.1"}
            or parsed.path != "/acs_test"
        ):
            raise ValueError("ONLY_LOCAL_ACS_TEST_DATABASE_ALLOWED")
        self.clock = [1000.0]
        self.s = Store(self.url, clock=lambda: self.clock[0])
        self.s.initialize()
        with self.s.transaction() as conn:
            conn.execute(
                "TRUNCATE acs_events,acs_tasks,acs_agents,acs_outbox,acs_inbox"
            )
        self.owner = Principal("owner", "owner")
        self.agent = Principal("agent", "claude")

    def assignment(self):
        return {
            "version": 1,
            "event_id": "a",
            "kind": "assign",
            "task_id": "t",
            "agent": "claude",
            "action": "engineering",
            "objective": "https://github.com/jsp1440/orchid-calyx-backend/issues/1823",
        }

    def test_postgres_restart_dedup_response_and_outbox(self):
        event = self.assignment()
        task = self.s.apply(event, self.owner)
        other = Store(self.url, clock=lambda: 1000)
        self.assertEqual(other.apply(event, self.owner), task)
        lease = other.apply(
            {"version": 1, "event_id": "c", "kind": "claim", "task_id": "t"}, self.agent
        )
        result = other.apply(
            {
                "version": 1,
                "event_id": "r",
                "kind": "response",
                "task_id": "t",
                "lease_token": lease["lease_token"],
                "outcome": "delivered",
                "reference": "https://github.com/jsp1440/orchid-calyx-backend/pull/1",
            },
            self.agent,
        )
        self.assertEqual(result["state"], "delivered")
        self.assertEqual(self.s.task("t")["state"], "delivered")
        report = self.s.take_report()
        self.s.settle_report(report["id"], report["token"], True)
        self.assertEqual(len(self.s.reports()), 3)

    def test_postgres_concurrent_claim(self):
        self.s.apply(self.assignment(), self.owner)

        def attempt(i):
            try:
                Store(self.url, clock=lambda: 1000).apply(
                    {
                        "version": 1,
                        "event_id": f"c{i}",
                        "kind": "claim",
                        "task_id": "t",
                    },
                    self.agent,
                )
                return "running"
            except ValueError:
                return "refused"

        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            self.assertCountEqual(
                list(pool.map(attempt, range(2))), ["running", "refused"]
            )

    def test_postgres_expiry_and_gate(self):
        self.s.apply(self.assignment(), self.owner)
        self.s.apply(
            {"version": 1, "event_id": "c", "kind": "claim", "task_id": "t"}, self.agent
        )
        self.clock[0] += 61
        self.s.tick()
        self.assertEqual(self.s.task("t")["state"], "retry")
        gated = self.assignment()
        gated.update(event_id="g", task_id="g", action="deploy")
        self.assertEqual(self.s.apply(gated, self.owner)["state"], "owner_gate")

    def test_postgres_inbox_is_atomic(self):
        from coordination.github import Bridge

        class NoNetwork:
            reporter_ids = frozenset({99})

        import json

        bridge = Bridge(self.s, NoNetwork(), {1: self.owner})
        comment = {
            "id": 1,
            "body": "[OC-ACS-v1]\n```json\n" + json.dumps(self.assignment()) + "\n```",
            "user": {"id": 1},
        }
        self.assertEqual(bridge.ingest(comment), "accepted")
        self.assertEqual(bridge.ingest(comment), "ignored")
        with self.s.transaction() as conn:
            self.assertEqual(
                conn.execute("SELECT count(*) AS n FROM acs_inbox").fetchone()["n"], 1
            )
