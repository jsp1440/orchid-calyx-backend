import hashlib
import hmac
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from coordination.ingress import make_server
from coordination.store import Store


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.s = Store(str(Path(self.tmp.name) / "state.db"))
        self.s.initialize()
        self.keys = {
            name: {"secret": name * 32, "role": role, "name": name}
            for name, role in [("owner", "owner"), ("claude", "agent")]
        }
        self.woken = threading.Event()
        self.server = make_server(self.s, self.keys, port=0, on_event=self.woken.set)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()
        self.tmp.cleanup()

    def post(self, event, name="owner", tamper=False):
        body = json.dumps(event).encode()
        timestamp = str(time.time())
        signature = hmac.new(
            self.keys[name]["secret"].encode(),
            timestamp.encode() + b"." + body,
            hashlib.sha256,
        ).hexdigest()
        if tamper:
            body += b" "
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.server.server_port}/events",
            data=body,
            headers={
                "X-ACS-Key": name,
                "X-ACS-Time": timestamp,
                "X-ACS-Signature": signature,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as r:
            return r.code, json.load(r)

    def test_signed_http_roundtrip_and_immediate_wake(self):
        e = {
            "version": 1,
            "event_id": "a",
            "kind": "assign",
            "task_id": "t",
            "agent": "claude",
            "action": "engineering",
            "objective": "https://github.com/jsp1440/orchid-calyx-backend/issues/1823",
        }
        self.assertEqual(self.post(e)[0], 200)
        self.assertTrue(self.woken.wait(1))
        status, lease = self.post(
            {"version": 1, "event_id": "c", "kind": "claim", "task_id": "t"}, "claude"
        )
        self.assertEqual(status, 200)
        for event_id, kind, extra in [
            ("h", "heartbeat", {}),
            (
                "r",
                "response",
                {
                    "outcome": "delivered",
                    "reference": "https://github.com/jsp1440/orchid-calyx-backend/pull/1",
                },
            ),
        ]:
            status, result = self.post(
                dict(
                    version=1,
                    event_id=event_id,
                    kind=kind,
                    task_id="t",
                    lease_token=lease["lease_token"],
                    **extra,
                ),
                "claude",
            )
            self.assertEqual(status, 200)
        self.assertEqual(result["state"], "delivered")

    def test_tampered_request_does_not_write(self):
        self.assertEqual(self.post({}, tamper=True)[0], 403)
        self.assertEqual(self.s.events(), [])

    def test_server_refuses_public_plaintext_binding(self):
        with self.assertRaises(ValueError):
            make_server(self.s, self.keys, host="0.0.0.0")

    def test_signed_github_webhook_scope_and_replay(self):
        from coordination.github import Bridge
        from coordination.store import Principal

        class NoNetwork:
            reporter_ids = frozenset({99})

        bridge = Bridge(self.s, NoNetwork(), {1: Principal("owner", "owner")})
        secret = "webhook-secret" * 4
        server = make_server(
            self.s,
            self.keys,
            port=0,
            bridge=bridge,
            webhook_secret=secret,
            on_event=self.woken.set,
        )
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        event = {
            "version": 1,
            "event_id": "webhook-a",
            "kind": "assign",
            "task_id": "webhook-t",
            "agent": "claude",
            "action": "engineering",
            "objective": "https://github.com/jsp1440/orchid-calyx-backend/issues/1823",
        }
        payload = {
            "action": "created",
            "repository": {"full_name": "jsp1440/orchid-calyx-backend"},
            "issue": {"number": 1823},
            "comment": {
                "id": 777,
                "user": {"id": 1},
                "body": "[OC-ACS-v1]\n```json\n" + json.dumps(event) + "\n```",
            },
        }
        try:
            for scope, expected in [(1823, 200), (1823, 200), (1, 400)]:
                payload["issue"]["number"] = scope
                body = json.dumps(payload).encode()
                signature = (
                    "sha256="
                    + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
                )
                req = urllib.request.Request(
                    f"http://127.0.0.1:{server.server_port}/github/events",
                    data=body,
                    headers={
                        "X-Hub-Signature-256": signature,
                        "X-GitHub-Event": "issue_comment",
                    },
                )
                try:
                    with urllib.request.urlopen(req, timeout=5) as r:
                        status = r.status
                except urllib.error.HTTPError as r:
                    status = r.code
                self.assertEqual(status, expected)
            self.assertEqual(len(self.s.events()), 1)
        finally:
            server.shutdown()
            worker.join()
            server.server_close()
