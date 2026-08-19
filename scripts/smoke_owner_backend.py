"""Smoke-test the deployed owner-session and Mission Control backend.

Transport note
--------------
``POST /api/mission-control/owner/session`` delivers the signed owner session as
an ``HttpOnly`` cookie and deliberately returns the literal string ``"cookie"``
in the JSON ``token`` field, so the credential is never readable from a response
body. An earlier revision of this script treated that literal as a bearer token,
which produced two false passes (``owner_session`` and ``owner_session_validate``
both assert only ``status == 200``, and the unauthenticated ``GET /session``
answers ``200 {"authenticated": false}``) followed by a real ``401`` on the first
endpoint that actually verifies the credential. This script therefore carries a
cookie jar and asserts the authenticated *state*, not merely the status code.
"""

from __future__ import annotations

import json
import os
import sys
from http.cookiejar import CookieJar
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener

BASE_URL = os.environ.get(
    "CALYX_BACKEND_URL", "https://orchid-calyx-backend.onrender.com"
).rstrip("/")
ACCESS_CODE = os.environ.get("CALYX_OWNER_ACCESS_CODE", "")
OWNER_SESSION_COOKIE = "calyx_owner_session"

_JAR = CookieJar()
_OPENER = build_opener(HTTPCookieProcessor(_JAR))


def request(
    path: str,
    *,
    method: str = "GET",
    payload: dict | None = None,
    token: str = "",
) -> tuple[int, dict]:
    """Perform one request, returning ``(status, body)``.

    HTTP error responses are returned rather than raised so that a single failing
    check cannot abort the remaining checks.
    """
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(f"{BASE_URL}{path}", data=data, headers=headers, method=method)
    try:
        with _OPENER.open(req, timeout=30) as response:
            body = response.read().decode()
            return response.status, json.loads(body) if body else {}
    except HTTPError as exc:
        body = exc.read().decode(errors="replace")
        try:
            return exc.code, json.loads(body) if body else {}
        except json.JSONDecodeError:
            return exc.code, {"detail": body[:200]}


def session_cookie_present() -> bool:
    return any(cookie.name == OWNER_SESSION_COOKIE for cookie in _JAR)


def bearer_from(session: dict) -> str:
    """Return a usable bearer token, ignoring the ``"cookie"`` transport sentinel."""
    candidate = session.get("token") or session.get("access_token") or ""
    return "" if candidate == "cookie" else str(candidate)


def main() -> int:
    checks: list[tuple[str, bool, str]] = []

    try:
        status, _ = request("/health")
        checks.append(("health", status == 200, str(status)))

        if not ACCESS_CODE:
            checks.append(("owner_session", False, "CALYX_OWNER_ACCESS_CODE not set"))
        else:
            status, session = request(
                "/api/mission-control/owner/session",
                method="POST",
                payload={"access_code": ACCESS_CODE},
            )
            token = bearer_from(session)
            credentialed = session_cookie_present() or bool(token)
            authenticated = session.get("authenticated") is True
            checks.append(
                (
                    "owner_session",
                    status == 200 and authenticated and credentialed,
                    f"status={status} authenticated={session.get('authenticated')} "
                    f"cookie={session_cookie_present()} bearer={bool(token)}",
                )
            )

            if credentialed:
                # The cookie jar supplies the credential; ``token`` stays empty
                # under the cookie transport and is only sent when the backend
                # genuinely returns a bearer.
                status, validated = request(
                    "/api/mission-control/owner/session", token=token
                )
                checks.append(
                    (
                        "owner_session_validate",
                        status == 200 and validated.get("authenticated") is True,
                        f"status={status} authenticated={validated.get('authenticated')}",
                    )
                )

                status, permissions = request(
                    "/api/mission-control/owner/permissions", token=token
                )
                checks.append(
                    (
                        "owner_permissions",
                        status == 200 and bool(permissions.get("allowedActions")),
                        f"status={status}",
                    )
                )

        status, _ = request("/brain/mission-control/chat/status")
        checks.append(("mission_control_chat", status == 200, str(status)))
        status, _ = request("/brain/mission-control/runtime/status")
        checks.append(("runtime_status", status == 200, str(status)))
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        checks.append(("request_failure", False, repr(exc)))

    for name, passed, detail in checks:
        print(f"{'PASS' if passed else 'FAIL'} {name}: {detail}")
    return 0 if checks and all(passed for _, passed, _ in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
