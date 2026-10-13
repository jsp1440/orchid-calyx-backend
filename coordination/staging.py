"""Explicit staging-only bootstrap; refuses ephemeral storage and all remote DBs."""

from __future__ import annotations

import json
import os
import signal
import threading
import time
from pathlib import Path

from .edge import make_edge
from .github import Bridge, GitHub, strict_json
from .ingress import make_server
from .store import AGENTS, Principal, Store


def validate_config(env, data_dir, *, mounted):
    if env.get("COORDINATOR_STAGE") != "staging" or env.get("COORDINATOR_DATABASE_URL"):
        raise ValueError("STAGING_LOCAL_STORE_ONLY")
    if not mounted or not data_dir.is_dir():
        raise ValueError("PERSISTENT_DISK_REQUIRED")
    keys = strict_json(env.get("COORDINATOR_INGRESS_KEYS", "{}"))
    if not isinstance(keys, dict) or not keys:
        raise ValueError("SEPARATE_INGRESS_KEYS_REQUIRED")
    secrets_seen = set()
    owner_count = 0
    names = set()
    for key_id, config in keys.items():
        if (
            not isinstance(key_id, str)
            or not isinstance(config, dict)
            or set(config) != {"role", "name", "secret"}
        ):
            raise ValueError("KEY_CONFIG_INVALID")
        secret = config["secret"]
        if not isinstance(secret, str) or len(secret) < 32 or secret in secrets_seen:
            raise ValueError("KEY_REUSE_OR_WEAK_SECRET")
        secrets_seen.add(secret)
        if config["role"] == "owner" and config["name"] == "owner":
            owner_count += 1
        elif config["role"] != "agent" or config["name"] not in AGENTS:
            raise ValueError("STAGING_KEY_SCOPE_INVALID")
        if config["name"] in names:
            raise ValueError("DUPLICATE_IDENTITY")
        names.add(config["name"])
    if owner_count != 1:
        raise ValueError("EXACTLY_ONE_OWNER_KEY_REQUIRED")
    return keys


def run_cycle(store, bridge):
    try:
        result = (
            {"status": "cycle", **bridge.cycle()}
            if bridge
            else {
                "status": "owner_gate",
                "reason": "github_reporter_credential_missing",
            }
        )
    except Exception:  # noqa: BLE001 - sanitize transport errors without disabling local recovery
        result = {"status": "blocked", "reason": "transport_unavailable"}
    try:
        store.tick()
    except Exception:  # noqa: BLE001 - independent local-store recovery boundary
        return {"status": "blocked", "reason": "store_unavailable"}
    return result


def main():
    data_dir = Path("/var/data")
    keys = validate_config(os.environ, data_dir, mounted=os.path.ismount(data_dir))
    os.umask(0o077)
    store = Store(str(data_dir / "acs-staging.sqlite3"))
    # Authorized new, dedicated local staging schema; never a production migration.
    store.initialize()
    token = os.environ.get("COORDINATOR_GITHUB_TOKEN")
    bridge = None
    if token:
        config = strict_json(os.environ.get("COORDINATOR_PRINCIPALS", "{}"))
        principals = {int(uid): Principal(**value) for uid, value in config.items()}
        reporter_ids = set(
            strict_json(os.environ.get("COORDINATOR_REPORTER_IDS", "[]"))
        )
        bridge = Bridge(store, GitHub(token, reporter_ids=reporter_ids), principals)
    wake = threading.Event()
    stop = threading.Event()
    ingress = make_server(
        store,
        keys,
        on_event=wake.set,
        bridge=bridge,
        webhook_secret=os.environ.get("COORDINATOR_WEBHOOK_SECRET"),
    )
    last_success = [0.0]
    edge = make_edge(
        int(os.environ.get("PORT", "10000")),
        ready=lambda: bridge is not None and time.time() - last_success[0] < 120,
    )
    servers = (ingress, edge)
    workers = []
    for server in servers:
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        workers.append(worker)

    def shutdown(*_):
        stop.set()
        wake.set()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    try:
        while not stop.is_set():
            wake.clear()
            result = run_cycle(store, bridge)
            last_success[0] = (
                time.time()
                if result["status"] == "cycle" and not result["report_failed"]
                else 0.0
            )
            print(json.dumps(result), flush=True)
            wake.wait(60)
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()
        for worker in workers:
            worker.join(timeout=5)


if __name__ == "__main__":
    main()
