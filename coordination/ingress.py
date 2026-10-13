"""HMAC-authenticated event ingress; signed identity comes from local configuration."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .github import strict_json
from .store import Principal, canonical


def authenticate(body, headers, keys, *, now=None):
    if len(body) > 16384:
        raise PermissionError("INGRESS_TOO_LARGE")
    config = keys.get(headers.get("X-ACS-Key"))
    timestamp = headers.get("X-ACS-Time", "")
    signature = headers.get("X-ACS-Signature", "")
    now = time.time() if now is None else now
    try:
        ts = float(timestamp)
    except (ValueError, TypeError):
        raise PermissionError("SIGNATURE_TIMESTAMP_INVALID") from None
    if (
        not config
        or not math.isfinite(ts)
        or abs(now - ts) > 300
        or len(config.get("secret", "")) < 32
    ):
        raise PermissionError("SIGNATURE_EXPIRED_OR_UNKNOWN")
    expected = hmac.new(
        config["secret"].encode(), timestamp.encode() + b"." + body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise PermissionError("SIGNATURE_INVALID")
    principal = Principal(config["role"], config["name"])
    principal.key()
    return principal


def make_server(
    store,
    keys,
    *,
    host="127.0.0.1",
    port=8765,
    on_event=lambda: None,
    bridge=None,
    webhook_secret=None,
):
    if host != "127.0.0.1":
        raise ValueError("LOOPBACK_ONLY_USE_AUTHENTICATED_TLS_PROXY")
    if not keys or any(len(c.get("secret", "")) < 32 for c in keys.values()):
        raise ValueError("INGRESS_KEYS_REQUIRED")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # Do not log bodies, lease tokens or auth headers.

        def do_POST(self):
            if self.path not in {"/events", "/github/events"}:
                self.reply(404, {"error": "NOT_FOUND"})
                return
            try:
                if self.headers.get("Transfer-Encoding"):
                    raise ValueError("CHUNKED_BODY_REFUSED")
                length = int(self.headers.get("Content-Length", "-1"))
                if not 0 < length <= 16384:
                    raise ValueError("CONTENT_LENGTH_INVALID")
                self.connection.settimeout(5)
                body = self.rfile.read(length)
                if len(body) != length:
                    raise ValueError("TRUNCATED_BODY")
                if self.path == "/github/events":
                    if not bridge or not webhook_secret or len(webhook_secret) < 32:
                        raise PermissionError("WEBHOOK_DISABLED")
                    signature = (
                        "sha256="
                        + hmac.new(
                            webhook_secret.encode(), body, hashlib.sha256
                        ).hexdigest()
                    )
                    if not hmac.compare_digest(
                        signature, self.headers.get("X-Hub-Signature-256", "")
                    ):
                        raise PermissionError("WEBHOOK_SIGNATURE_INVALID")
                    payload = strict_json(body)
                    if (
                        self.headers.get("X-GitHub-Event") != "issue_comment"
                        or payload.get("action") != "created"
                        or payload.get("repository", {}).get("full_name")
                        != "jsp1440/orchid-calyx-backend"
                        or payload.get("issue", {}).get("number") != 1823
                    ):
                        raise ValueError("WEBHOOK_SCOPE_REFUSED")
                    status = bridge.ingest(payload.get("comment", {}))
                    if status == "rejected":
                        raise PermissionError("WEBHOOK_EVENT_REFUSED")
                    on_event()
                    self.reply(200, {"status": status})
                    return
                principal = authenticate(body, self.headers, keys)
                event = strict_json(body)
                # Attempt-only messages are supported solely by verified GitHub author ingress.
                if isinstance(event, dict) and "attempt" in event:
                    raise ValueError("PRIVATE_INGRESS_REQUIRES_TOKEN")
                result = store.apply(event, principal)
                on_event()
                self.reply(200, result)
            except PermissionError:
                self.reply(403, {"error": "AUTHORITY_OR_LEASE_REFUSED"})
            except (ValueError, TypeError, KeyError, json.JSONDecodeError):
                self.reply(400, {"error": "EVENT_REFUSED"})
            except Exception:  # noqa: BLE001 - sanitize transport/storage errors at service boundary
                self.reply(503, {"error": "STORE_UNAVAILABLE"})

        def reply(self, code, result):
            payload = canonical(result).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server
