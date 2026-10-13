"""Operator entry point. No infrastructure or schema changes at runtime startup."""

from __future__ import annotations

import argparse
import json
import os
import signal
import threading

from .github import Bridge, GitHub, strict_json
from .ingress import make_server
from .store import Principal, Store


def main():
    parser = argparse.ArgumentParser(
        description="Independent Orchid Continuum engineering coordinator"
    )
    parser.add_argument("command", choices=("init", "once", "run", "health"))
    parser.add_argument(
        "--sqlite-path",
        help="Persistent local SQLite file, mutually exclusive with dedicated URL",
    )
    parser.add_argument(
        "--confirm-isolated-postgres",
        action="store_true",
        help="Explicit isolated database migration permission; never use production",
    )
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--interval",
        type=int,
        default=60,
        help="Recovery poll interval; signed events wake immediately",
    )
    args = parser.parse_args()
    dedicated_url = os.environ.get("COORDINATOR_DATABASE_URL")
    if args.sqlite_path and dedicated_url:
        parser.error("Choose exactly one dedicated store")
    if not 10 <= args.interval <= 300:
        parser.error("Interval must be between 10 and 300 seconds")
    url = args.sqlite_path or dedicated_url
    if not url:
        parser.error("Dedicated store required; DATABASE_URL is deliberately ignored")
    store = Store(url)
    if args.command == "init":
        if store.postgres and not args.confirm_isolated_postgres:
            parser.error(
                "PostgreSQL migration requires --confirm-isolated-postgres after owner authorization"
            )
        store.initialize()
        print(
            json.dumps({"status": "schema_initialized", "production_authorized": False})
        )
        return
    # Fail immediately if operator has not applied the isolated migration.
    store.events()
    if args.command == "health":
        print(json.dumps({"agents": store.health()}))
        return
    config = strict_json(os.environ.get("COORDINATOR_PRINCIPALS", "{}"))
    principals = {int(uid): Principal(**value) for uid, value in config.items()}
    reporter_ids = set(strict_json(os.environ.get("COORDINATOR_REPORTER_IDS", "[]")))
    bridge = Bridge(
        store,
        GitHub(os.environ.get("COORDINATOR_GITHUB_TOKEN"), reporter_ids=reporter_ids),
        principals,
    )
    if args.command == "once":
        print(json.dumps(bridge.cycle()))
        return
    keys = strict_json(os.environ.get("COORDINATOR_INGRESS_KEYS", "{}"))
    wake = threading.Event()
    stop = threading.Event()
    server = make_server(
        store,
        keys,
        port=args.port,
        on_event=wake.set,
        bridge=bridge,
        webhook_secret=os.environ.get("COORDINATOR_WEBHOOK_SECRET"),
    )
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    def shutdown(*_):
        stop.set()
        wake.set()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    try:
        while not stop.is_set():
            wake.clear()
            try:
                result = bridge.cycle()
                print(json.dumps({"status": "cycle", **result}), flush=True)
            except Exception:  # noqa: BLE001 - sanitize transport/storage errors at service boundary
                # Exception messages can contain URLs/credentials; publish only fixed code.
                print(
                    json.dumps(
                        {"status": "blocked", "reason": "github_or_store_unavailable"}
                    ),
                    flush=True,
                )
            # Local recovery must still expire leases during a GitHub outage.
            try:
                store.tick()
            except Exception:  # noqa: BLE001 - sanitize transport/storage errors at service boundary
                print(
                    json.dumps({"status": "blocked", "reason": "store_unavailable"}),
                    flush=True,
                )
            wake.wait(args.interval)
    finally:
        server.shutdown()
        server_thread.join(timeout=5)
        server.server_close()


if __name__ == "__main__":
    main()
