import tempfile
import unittest
from pathlib import Path

from coordination.store import Principal, Store


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.url = str(Path(self.tmp.name) / "state.db")
        self.clock = [1000.0]
        self.s = Store(self.url, clock=lambda: self.clock[0])
        self.s.initialize()
        self.owner = Principal("owner", "owner")
        self.agent = Principal("agent", "claude")

    def tearDown(self):
        self.tmp.cleanup()

    def event(self, kind, **data):
        return dict(
            version=1,
            event_id=f"e{len(self.s.events())}",
            kind=kind,
            task_id="t1",
            **data,
        )

    def assign(self, action="engineering"):
        e = self.event(
            "assign",
            agent="claude",
            objective="https://github.com/jsp1440/orchid-calyx-backend/issues/1823",
            action=action,
        )
        return e, self.s.apply(e, self.owner)

    def claim(self):
        return self.s.apply(self.event("claim"), self.agent)

    def test_restart_and_duplicate(self):
        e, row = self.assign()
        other = Store(self.url, clock=lambda: self.clock[0])
        self.assertEqual(other.task("t1")["state"], "queued")
        self.assertEqual(other.apply(e, self.owner), row)
        e["agent"] = "kimi"
        with self.assertRaises(ValueError):
            other.apply(e, self.owner)

    def test_duplicate_principal_cannot_read_receipt(self):
        e, _ = self.assign()
        with self.assertRaises(PermissionError):
            self.s.apply(e, self.agent)

    def test_claim_fencing_and_retry(self):
        self.assign()
        first = self.claim()
        with self.assertRaises(ValueError):
            self.claim()
        self.clock[0] += 61
        self.s.tick()
        self.assertEqual(self.s.task("t1")["state"], "retry")
        with self.assertRaises(ValueError):
            self.claim()
        self.clock[0] += 10
        second = self.claim()
        self.assertNotEqual(first["lease_token"], second["lease_token"])
        with self.assertRaises(PermissionError):
            self.s.apply(
                self.event(
                    "response",
                    lease_token=first["lease_token"],
                    outcome="delivered",
                    reference="https://github.com/jsp1440/orchid-calyx-backend/pull/1",
                ),
                self.agent,
            )

    def test_response_atomic_report_and_restart(self):
        self.assign()
        lease = self.claim()
        self.s.apply(
            self.event("heartbeat", lease_token=lease["lease_token"]), self.agent
        )
        self.s.apply(
            self.event(
                "response",
                lease_token=lease["lease_token"],
                outcome="delivered",
                reference="https://github.com/jsp1440/orchid-calyx-backend/pull/1",
            ),
            self.agent,
        )
        self.assertEqual(Store(self.url).task("t1")["state"], "delivered")
        self.assertTrue(any("delivered" in r["body"] for r in self.s.reports()))
        self.assertFalse(
            any(lease["lease_token"] in r["body"] for r in self.s.reports())
        )

    def test_gated_actions_never_claimable(self):
        _, task = self.assign("paid_ai")
        self.assertEqual(task["state"], "owner_gate")
        with self.assertRaises(PermissionError):
            self.s.apply(
                self.event("approve", digest=task["digest"], expires_at=1100),
                self.agent,
            )
        self.s.apply(
            self.event("approve", digest=task["digest"], expires_at=1100), self.owner
        )
        with self.assertRaises(ValueError):
            self.claim()
        self.assertEqual(self.s.task("t1")["state"], "owner_gate")

    def test_dead_letter_and_deadline(self):
        self.assign()
        for attempt in range(3):
            self.claim()
            self.clock[0] += 61
            self.s.tick()
            self.clock[0] += 40
        self.assertEqual(self.s.task("t1")["state"], "dead_letter")

    def test_unknown_fields_and_identity(self):
        e, _ = self.assign()
        e["event_id"] = "changed"
        e["execute"] = True
        with self.assertRaises(ValueError):
            self.s.apply(e, self.owner)
        with self.assertRaises(PermissionError):
            self.s.apply(self.event("claim"), Principal("agent", "kimi"))

    def test_report_recovery_and_stale_ack(self):
        self.assign()
        report = self.s.take_report()
        self.assertIsNone(self.s.take_report())
        self.clock[0] += 61
        recovered = self.s.take_report()
        with self.assertRaises(PermissionError):
            self.s.settle_report(report["id"], report["token"], True)
        self.s.settle_report(recovered["id"], recovered["token"], True)
        self.assertIsNone(self.s.take_report())

    def test_two_store_claims_only_one_wins(self):
        import concurrent.futures

        self.assign()

        def claim(i):
            try:
                return Store(self.url, clock=lambda: 1000).apply(
                    {
                        "version": 1,
                        "event_id": f"claim-{i}",
                        "kind": "claim",
                        "task_id": "t1",
                    },
                    self.agent,
                )["state"]
            except ValueError:
                return "refused"

        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            self.assertCountEqual(
                list(pool.map(claim, range(2))), ["running", "refused"]
            )

    def test_heartbeat_cannot_extend_attempt_forever(self):
        self.assign()
        lease = self.claim()
        for _ in range(14):
            self.clock[0] += 59
            self.s.apply(
                self.event("heartbeat", lease_token=lease["lease_token"]), self.agent
            )
        self.clock[0] = 1900
        with self.assertRaises(PermissionError):
            self.s.apply(
                self.event("heartbeat", lease_token=lease["lease_token"]), self.agent
            )
        self.s.tick()
        self.assertEqual(self.s.task("t1")["state"], "retry")

    def test_approval_digest_and_expiry(self):
        _, task = self.assign("deploy")
        with self.assertRaises(ValueError):
            self.s.apply(
                self.event("approve", digest="0" * 64, expires_at=1100), self.owner
            )
        self.s.apply(
            self.event("approve", digest=task["digest"], expires_at=1100), self.owner
        )
        self.clock[0] = 1101
        self.s.tick()
        self.assertIsNone(self.s.task("t1")["approval_until"])
        self.assertEqual(self.s.task("t1")["reason"], "owner_approval_expired")

    def test_unknown_and_stale_agents_are_distinct(self):
        self.assertEqual(self.s.health()["kimi"]["status"], "unknown")
        self.assign()
        self.claim()
        self.assertEqual(self.s.health()["claude"]["status"], "healthy")
        self.clock[0] += 60
        self.assertEqual(self.s.health()["claude"]["status"], "stale")

    def test_user_event_cannot_suppress_generated_timeout_report(self):
        e = {
            "version": 1,
            "event_id": "timeout:t1:1",
            "kind": "assign",
            "task_id": "t1",
            "agent": "claude",
            "action": "engineering",
            "objective": "https://github.com/jsp1440/orchid-calyx-backend/issues/1823",
        }
        self.s.apply(e, self.owner)
        self.claim()
        self.clock[0] += 61
        self.s.tick()
        self.assertTrue(any('"state":"retry"' in r["body"] for r in self.s.reports()))
