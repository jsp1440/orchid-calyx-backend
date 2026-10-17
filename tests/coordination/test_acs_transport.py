import hashlib
import hmac
import json
import tempfile
import unittest
from pathlib import Path

from coordination.github import Bridge, GitHub
from coordination.ingress import authenticate
from coordination.store import Principal, Store


class FakeGitHub:
    def __init__(self):
        self.items = []
        self.reporter_ids = {99}
        self.fail_after_post = False

    def comments(self):
        return list(self.items)

    def post(self, body):
        self.items.append(
            {
                "id": len(self.items) + 1,
                "body": body,
                "user": {"id": 99},
                "created_at": "2026-10-13T00:00:00Z",
            }
        )
        if self.fail_after_post:
            self.fail_after_post = False
            raise TimeoutError()


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.clock = [1000.0]
        self.s = Store(
            str(Path(self.tmp.name) / "state.db"), clock=lambda: self.clock[0]
        )
        self.s.initialize()
        self.gh = FakeGitHub()
        self.b = Bridge(
            self.s,
            self.gh,
            {1: Principal("owner", "owner"), 2: Principal("agent", "claude")},
        )

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, event, user=1):
        self.gh.items.append(
            {
                "id": len(self.gh.items) + 1,
                "body": "[OC-ACS-v1]\n```json\n" + json.dumps(event) + "\n```",
                "user": {"id": user},
            }
        )

    def assignment(self):
        return {
            "version": 1,
            "event_id": "assign1",
            "task_id": "t1",
            "kind": "assign",
            "agent": "claude",
            "action": "engineering",
            "objective": "https://github.com/jsp1440/orchid-calyx-backend/issues/1823",
        }

    def test_github_roundtrip_and_restart(self):
        self.add(self.assignment())
        self.b.cycle()
        self.add(
            {"version": 1, "event_id": "claim1", "task_id": "t1", "kind": "claim"}, 2
        )
        self.b.cycle()
        self.add(
            {
                "version": 1,
                "event_id": "heartbeat1",
                "task_id": "t1",
                "kind": "heartbeat",
                "attempt": 1,
            },
            2,
        )
        self.b.cycle()
        self.add(
            {
                "version": 1,
                "event_id": "reply1",
                "task_id": "t1",
                "kind": "response",
                "attempt": 1,
                "outcome": "delivered",
                "reference": "https://github.com/jsp1440/orchid-calyx-backend/pull/1",
            },
            2,
        )
        self.b.cycle()
        self.assertEqual(self.s.task("t1")["state"], "delivered")
        posts = len(self.gh.items)
        Bridge(
            Store(self.s.url, clock=lambda: 1000), self.gh, self.b.principals
        ).cycle()
        self.assertEqual(len(self.gh.items), posts)
        self.assertTrue(all("lease_token" not in c["body"] for c in self.gh.items))

    def test_unknown_author_and_owner_spoof_refused(self):
        self.add(self.assignment(), 88)
        self.add(self.assignment(), 2)
        result = self.b.cycle()
        self.assertEqual(result["rejected"], 2)
        self.assertEqual(self.s.events(), [])

    def test_ambiguous_post_reconciles_no_duplicate(self):
        self.add(self.assignment())
        self.gh.fail_after_post = True
        self.b.cycle()
        count = len(self.gh.items)
        self.clock[0] += 10
        self.b.cycle()
        self.assertEqual(len(self.gh.items), count)
        self.assertEqual(self.s.reports()[0]["state"], "sent")

    def test_fake_marker_by_untrusted_author_cannot_suppress_report(self):
        self.add(self.assignment())
        self.gh.items.append(
            {"id": 2, "body": "<!-- OC-ACS:assign1 -->", "user": {"id": 88}}
        )
        self.b.cycle()
        self.assertEqual(len(self.gh.items), 3)

    def test_duplicate_json_keys_refused(self):
        self.gh.items.append(
            {
                "id": 1,
                "body": '[OC-ACS-v1]\n```json\n{"kind":"claim","kind":"assign"}\n```',
                "user": {"id": 1},
            }
        )
        self.assertEqual(self.b.cycle()["rejected"], 1)

    def test_old_attempt_cannot_complete_new_lease(self):
        self.add(self.assignment())
        self.b.cycle()
        self.add(
            {"version": 1, "event_id": "claim1", "task_id": "t1", "kind": "claim"}, 2
        )
        self.b.cycle()
        self.clock[0] += 61
        self.b.cycle()
        self.clock[0] += 10
        self.add(
            {"version": 1, "event_id": "claim2", "task_id": "t1", "kind": "claim"}, 2
        )
        self.b.cycle()
        self.add(
            {
                "version": 1,
                "event_id": "reply1",
                "task_id": "t1",
                "kind": "response",
                "attempt": 1,
                "outcome": "delivered",
                "reference": "https://github.com/jsp1440/orchid-calyx-backend/pull/1",
            },
            2,
        )
        self.assertEqual(self.b.cycle()["rejected"], 1)
        self.assertEqual(self.s.task("t1")["state"], "running")

    def test_signature_tamper_expiry_and_principal_binding(self):
        body = b'{"hello":"world"}'
        secret = "x" * 32
        sig = hmac.new(secret.encode(), b"1000." + body, hashlib.sha256).hexdigest()
        headers = {"X-ACS-Key": "claude", "X-ACS-Time": "1000", "X-ACS-Signature": sig}
        keys = {"claude": {"secret": secret, "role": "agent", "name": "claude"}}
        self.assertEqual(
            authenticate(body, headers, keys, now=1000), Principal("agent", "claude")
        )
        for payload, ts in [(body + b" ", 1000), (body, 1400)]:
            with self.assertRaises(PermissionError):
                authenticate(payload, headers, keys, now=ts)

    def test_github_pagination(self):
        gh = GitHub("fake", reporter_ids={99})
        pages = []

        def request(method, path, body=None):
            pages.append(path)
            return (
                [{"id": i} for i in range(100)] if "&page=1" in path else [{"id": 101}]
            )

        gh.request = request
        self.assertEqual(len(gh.comments()), 101)
        self.assertEqual(len(pages), 2)

    def test_refused_claim_does_not_execute_on_later_retry(self):
        self.add(self.assignment())
        self.b.cycle()
        self.add(
            {"version": 1, "event_id": "claim1", "task_id": "t1", "kind": "claim"}, 2
        )
        self.add(
            {"version": 1, "event_id": "too-soon", "task_id": "t1", "kind": "claim"}, 2
        )
        self.b.cycle()
        self.clock[0] += 61
        self.b.cycle()
        self.clock[0] += 10
        self.b.cycle()
        self.assertEqual(self.s.task("t1")["state"], "retry")
        self.assertEqual(self.s.task("t1")["attempts"], 1)

    def test_edit_cannot_change_assignment(self):
        self.add(self.assignment())
        self.b.cycle()
        event = self.assignment()
        event["event_id"] = "different"
        event["task_id"] = "injected"
        self.gh.items[0]["body"] = (
            "[OC-ACS-v1]\n```json\n" + json.dumps(event) + "\n```"
        )
        self.b.cycle()
        with self.assertRaises(ValueError):
            self.s.task("injected")

    def test_final_ambiguous_delivery_reconciles(self):
        self.s.max_attempts = 1
        self.add(self.assignment())
        self.gh.fail_after_post = True
        self.b.cycle()
        count = len(self.gh.items)
        self.clock[0] += 10
        self.b.cycle()
        self.assertEqual(len(self.gh.items), count)
        self.assertEqual(self.s.reports()[0]["state"], "sent")

    def test_final_post_crash_reconciles_without_another_send(self):
        self.s.max_attempts = 1
        self.add(self.assignment())
        self.b.ingest(self.gh.items[0])
        report = self.s.take_report()
        self.gh.post(report["body"])
        self.clock[0] += 61
        self.b.cycle()
        self.assertEqual(self.s.reports()[0]["state"], "sent")
        self.assertEqual(len(self.gh.items), 2)

    def test_final_unsent_crash_dead_letters_without_another_send(self):
        self.s.max_attempts = 1
        self.add(self.assignment())
        self.b.ingest(self.gh.items[0])
        self.s.take_report()
        self.clock[0] += 61
        self.b.cycle()
        self.assertEqual(self.s.reports()[0]["state"], "dead_letter")
        self.assertEqual(len(self.gh.items), 1)
