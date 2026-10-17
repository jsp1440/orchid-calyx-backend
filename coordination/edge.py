"""Bounded public forwarding edge for the owner-authorized Render staging pilot.

Render terminates TLS. Secrets and task state are handled only by loopback
signed ingress; this proxy has one fixed upstream and exposes no read API.
"""

from __future__ import annotations

import http.client
import json
from http.server import BaseHTTPRequestHandler

from .http_server import BoundedHTTPServer

AUTH_HEADERS = (
    "X-ACS-Key",
    "X-ACS-Time",
    "X-ACS-Signature",
    "X-Hub-Signature-256",
    "X-GitHub-Event",
)


def make_edge(port, *, upstream_port=8765, host="0.0.0.0", ready=lambda: False):
    if not 1024 <= upstream_port <= 65535:
        raise ValueError("UPSTREAM_PORT_INVALID")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, status, body):
            payload = json.dumps(body, separators=(",", ":")).encode()
            self.raw_reply(status, payload)

        def raw_reply(self, status, payload):
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            if self.path not in {"/healthz", "/readyz"}:
                self.reply(404, {"error": "NOT_FOUND"})
                return
            is_ready = bool(ready())
            self.reply(
                200 if self.path == "/healthz" or is_ready else 503,
                {"status": "alive", "stage": "staging", "ready": is_ready},
            )

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
                headers = {
                    h: self.headers[h] for h in AUTH_HEADERS if h in self.headers
                }
                headers["Content-Type"] = "application/json"
                conn = http.client.HTTPConnection(
                    "127.0.0.1", upstream_port, timeout=10
                )
                try:
                    conn.request("POST", self.path, body=body, headers=headers)
                    response = conn.getresponse()
                    payload = response.read(65537)
                    if len(payload) > 65536:
                        raise ValueError("UPSTREAM_RESPONSE_TOO_LARGE")
                    self.raw_reply(response.status, payload)
                finally:
                    conn.close()
            except (ValueError, TypeError):
                self.reply(400, {"error": "REQUEST_REFUSED"})
            except (OSError, http.client.HTTPException):
                self.reply(503, {"error": "INGRESS_UNAVAILABLE"})

    server = BoundedHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server
