import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from coordination.edge import make_edge
from coordination.staging import validate_config


class StagingTests(unittest.TestCase):
    def config(self):
        return {
            "COORDINATOR_STAGE": "staging",
            "COORDINATOR_INGRESS_KEYS": json.dumps(
                {
                    "owner": {"role": "owner", "name": "owner", "secret": "o" * 64},
                    "claude": {"role": "agent", "name": "claude", "secret": "c" * 64},
                }
            ),
        }

    def test_bootstrap_requires_disk_and_refuses_remote_database(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                validate_config(self.config(), Path(d), mounted=False)
            env = self.config()
            env["COORDINATOR_DATABASE_URL"] = "postgresql://example.invalid/production"
            with self.assertRaises(ValueError):
                validate_config(env, Path(d), mounted=True)
            self.assertEqual(
                validate_config(self.config(), Path(d), mounted=True)["owner"]["role"],
                "owner",
            )

    def test_owner_key_cannot_be_reused_for_an_agent(self):
        env = self.config()
        keys = json.loads(env["COORDINATOR_INGRESS_KEYS"])
        keys["claude"]["secret"] = keys["owner"]["secret"]
        env["COORDINATOR_INGRESS_KEYS"] = json.dumps(keys)
        with self.assertRaises(ValueError):
            validate_config(env, Path("/var/data"), mounted=True)

    def test_edge_health_has_no_secret_or_task(self):
        server = make_edge(0, upstream_port=8765, host="127.0.0.1", ready=lambda: False)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{server.server_port}/healthz"
            ) as response:
                payload = json.load(response)
            self.assertEqual(
                payload, {"status": "alive", "stage": "staging", "ready": False}
            )
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/readyz")
            self.assertEqual(error.exception.code, 503)
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/tasks")
            self.assertEqual(error.exception.code, 404)
        finally:
            server.shutdown()
            worker.join()
            server.server_close()

    def test_edge_preserves_signed_body_and_refuses_tampering(self):
        import hashlib
        import hmac
        import time

        from coordination.ingress import make_server
        from coordination.store import Store

        with tempfile.TemporaryDirectory() as d:
            store = Store(str(Path(d) / "edge.db"))
            store.initialize()
            keys = json.loads(self.config()["COORDINATOR_INGRESS_KEYS"])
            ingress = make_server(store, keys, port=0)
            edge = make_edge(0, upstream_port=ingress.server_port, host="127.0.0.1")
            workers = []
            for server in (ingress, edge):
                worker = threading.Thread(target=server.serve_forever, daemon=True)
                worker.start()
                workers.append(worker)
            try:
                event = {
                    "version": 1,
                    "event_id": "edge-a",
                    "kind": "assign",
                    "task_id": "edge-t",
                    "agent": "claude",
                    "action": "engineering",
                    "objective": "https://github.com/jsp1440/orchid-calyx-backend/issues/1823",
                }
                body = json.dumps(event).encode()
                timestamp = str(time.time())
                signature = hmac.new(
                    keys["owner"]["secret"].encode(),
                    timestamp.encode() + b"." + body,
                    hashlib.sha256,
                ).hexdigest()
                headers = {
                    "X-ACS-Key": "owner",
                    "X-ACS-Time": timestamp,
                    "X-ACS-Signature": signature,
                }
                url = f"http://127.0.0.1:{edge.server_port}/events"
                with urllib.request.urlopen(
                    urllib.request.Request(url, data=body, headers=headers)
                ) as response:
                    self.assertEqual(response.status, 200)
                self.assertEqual(store.task("edge-t")["state"], "queued")
                for altered in (body + b" ", b"{}"):
                    with self.assertRaises(urllib.error.HTTPError) as error:
                        urllib.request.urlopen(
                            urllib.request.Request(url, data=altered, headers=headers)
                        )
                    self.assertEqual(error.exception.code, 403)
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(
                        urllib.request.Request(url, data=b"x" * 16385, headers=headers)
                    )
                self.assertEqual(error.exception.code, 400)
            finally:
                for server in (ingress, edge):
                    server.shutdown()
                    server.server_close()
                for worker in workers:
                    worker.join()
