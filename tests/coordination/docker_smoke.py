"""Disposable Docker persistence proof. Fixture keys never touch Render or GitHub."""

from __future__ import annotations

import hashlib
import hmac
import json
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

URL = "http://127.0.0.1:10001"
NAME = "acs-staging-smoke"
KEYS = {
    "owner": {"role": "owner", "name": "owner", "secret": "fixture-owner-" * 8},
    "claude": {"role": "agent", "name": "claude", "secret": "fixture-claude-" * 8},
}


def ready():
    for _ in range(150):
        try:
            with urllib.request.urlopen(URL + "/healthz", timeout=1) as response:
                assert json.load(response) == {
                    "status": "alive",
                    "stage": "staging",
                    "ready": False,
                }
                return
        except (OSError, ValueError):
            threading.Event().wait(0.2)
    raise RuntimeError("STAGING_CONTAINER_NOT_ALIVE")


def post(event, key="owner", *, tamper=False):
    body = json.dumps(event).encode()
    timestamp = str(time.time())
    signature = hmac.new(
        KEYS[key]["secret"].encode(), timestamp.encode() + b"." + body, hashlib.sha256
    ).hexdigest()
    if tamper:
        body += b" "
    request = urllib.request.Request(
        URL + "/events",
        data=body,
        headers={
            "X-ACS-Key": key,
            "X-ACS-Time": timestamp,
            "X-ACS-Signature": signature,
        },
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.load(response)


def main():
    with tempfile.TemporaryDirectory(prefix="acs-docker-test-") as folder:
        root = Path(folder)
        disk = root / "data"
        disk.mkdir()
        env = root / "fixture.env"
        env.write_text(
            "COORDINATOR_STAGE=staging\nCOORDINATOR_INGRESS_KEYS="
            + json.dumps(KEYS)
            + "\n"
        )
        env.chmod(0o600)
        subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                NAME,
                "-p",
                "127.0.0.1:10001:10000",
                "-v",
                f"{disk}:/var/data",
                "--env-file",
                str(env),
                "acs-staging-test",
            ],
            check=True,
            capture_output=True,
        )
        try:
            ready()
            assignment = {
                "version": 1,
                "event_id": "docker-a",
                "kind": "assign",
                "task_id": "docker-t",
                "agent": "claude",
                "action": "engineering",
                "objective": "https://github.com/jsp1440/orchid-calyx-backend/issues/1823",
            }
            assert post(assignment)["state"] == "queued"
            lease = post(
                {
                    "version": 1,
                    "event_id": "docker-c",
                    "kind": "claim",
                    "task_id": "docker-t",
                },
                "claude",
            )
            assert lease["state"] == "running"
            try:
                post(assignment, tamper=True)
            except urllib.error.HTTPError as error:
                assert error.code == 403
            else:
                raise AssertionError("TAMPERED_SIGNATURE_ACCEPTED")
            subprocess.run(["docker", "restart", NAME], check=True, capture_output=True)
            ready()
            result = post(
                {
                    "version": 1,
                    "event_id": "docker-r",
                    "kind": "response",
                    "task_id": "docker-t",
                    "lease_token": lease["lease_token"],
                    "outcome": "blocked",
                    "reference": "https://github.com/jsp1440/orchid-calyx-backend/pull/1833",
                },
                "claude",
            )
            assert result["state"] == "blocked"
            assert (disk / "acs-staging.sqlite3").is_file()
            print(
                "Docker smoke passed: TLS-edge contract, signature refusal, mounted SQLite, restart lease recovery; GitHub transport correctly not ready without credential."
            )
        finally:
            subprocess.run(
                ["docker", "rm", "-f", NAME], check=False, capture_output=True
            )


if __name__ == "__main__":
    main()
