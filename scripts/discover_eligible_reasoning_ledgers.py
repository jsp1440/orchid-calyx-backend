from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

OUTPUT_PATH = Path("calyx-eligible-ledger-discovery.json")
DEFAULT_BASE_URL = "https://orchid-calyx-backend.onrender.com"
BASE_URL = os.environ.get("CALYX_BACKEND_URL", DEFAULT_BASE_URL).strip().rstrip("/")
ACCESS_CODE = os.environ.get("CALYX_OWNER_ACCESS_CODE", "").strip()
TRANSIENT_HTTP_STATUSES = frozenset({502, 503, 504})
MAX_TRANSIENT_ATTEMPTS = 3


@dataclass(frozen=True, slots=True)
class DiscoveryFailure(RuntimeError):
    stage: str
    code: str
    message: str
    http_status: int | None = None
    attempts: int = 1

    def __str__(self) -> str:
        return self.message


def _canonical_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _base_url() -> str:
    return BASE_URL.strip().rstrip("/")


def _access_code() -> str:
    return ACCESS_CODE.strip()


def call(
    path: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    token: str = "",
    *,
    base_url: str | None = None,
    opener: Callable[..., Any] = urlopen,
    sleep: Callable[[float], None] = time.sleep,
    max_attempts: int = MAX_TRANSIENT_ATTEMPTS,
) -> tuple[int, dict[str, Any]]:
    """Call a read-only discovery dependency with bounded transient retries.

    The two-value return shape is intentionally preserved for existing operators and
    tests. Retry counts are surfaced on terminal failures through DiscoveryFailure.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"{(base_url or _base_url()).rstrip('/')}{path}"

    for attempt in range(1, max_attempts + 1):
        req = Request(url, data=data, headers=headers, method=method)
        try:
            with opener(req, timeout=45) as response:
                body = response.read().decode()
                parsed = json.loads(body) if body else {}
                if not isinstance(parsed, dict):
                    raise DiscoveryFailure(
                        stage="response",
                        code="INVALID_RESPONSE_BODY",
                        message="backend response must be a JSON object",
                        http_status=response.status,
                        attempts=attempt,
                    )
                return response.status, parsed
        except HTTPError as exc:
            if exc.code in TRANSIENT_HTTP_STATUSES and attempt < max_attempts:
                sleep(float(attempt))
                continue
            raise DiscoveryFailure(
                stage="http",
                code="BACKEND_HTTP_ERROR",
                message=f"backend returned HTTP {exc.code}",
                http_status=exc.code,
                attempts=attempt,
            ) from exc
        except URLError as exc:
            if attempt < max_attempts:
                sleep(float(attempt))
                continue
            raise DiscoveryFailure(
                stage="network",
                code="BACKEND_NETWORK_ERROR",
                message=f"backend request failed: {type(exc.reason).__name__}",
                attempts=attempt,
            ) from exc

    raise AssertionError("unreachable")


def _base_receipt(*, base_url: str) -> dict[str, Any]:
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "backend_url": base_url,
        "read_only": True,
        "production_mutation": False,
        "publication_endpoint_invoked": False,
    }


def discover(
    *,
    base_url: str | None = None,
    access_code: str | None = None,
    opener: Callable[..., Any] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    resolved_base_url = (base_url or _base_url()).strip().rstrip("/")
    resolved_access_code = _access_code() if access_code is None else access_code.strip()
    if not resolved_access_code:
        raise DiscoveryFailure(
            stage="configuration",
            code="OWNER_ACCESS_CODE_MISSING",
            message="owner access code is required",
        )

    call_kwargs: dict[str, Any] = {}
    if base_url is not None:
        call_kwargs["base_url"] = resolved_base_url
    if opener is not None:
        call_kwargs["opener"] = opener
    if sleep is not None:
        call_kwargs["sleep"] = sleep

    session_status, session = call(
        "/api/mission-control/owner/session-token",
        method="POST",
        payload={"access_code": resolved_access_code},
        **call_kwargs,
    )
    token = session.get("token") or session.get("access_token") or ""
    if session_status != 200 or not isinstance(token, str) or not token:
        raise DiscoveryFailure(
            stage="owner_session",
            code="OWNER_SESSION_UNAVAILABLE",
            message="owner session unavailable",
            http_status=session_status,
        )

    discovery_status, report = call(
        "/api/reasoning-ledgers/eligible-for-publication",
        token=token,
        **call_kwargs,
    )
    if discovery_status != 200:
        raise DiscoveryFailure(
            stage="discovery",
            code="DISCOVERY_HTTP_STATUS_UNEXPECTED",
            message=f"discovery returned HTTP {discovery_status}",
            http_status=discovery_status,
        )

    result = dict(report)
    result.update(
        {
            **_base_receipt(base_url=resolved_base_url),
            "status": "success",
            "owner_session_status": session_status,
            "discovery_status": discovery_status,
        }
    )
    result["artifact_hash"] = _canonical_hash(result)
    return result


def failure_receipt(failure: DiscoveryFailure, *, base_url: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        **_base_receipt(base_url=(base_url or _base_url()).strip().rstrip("/")),
        "status": "failed",
        "failure_stage": failure.stage,
        "failure_code": failure.code,
        "failure_message": failure.message,
        "http_status": failure.http_status,
        "attempts": failure.attempts,
        "eligible_count": None,
        "eligible_ledgers": [],
    }
    result["artifact_hash"] = _canonical_hash(result)
    return result


def _write_receipt(result: dict[str, Any], *, output_path: Path = OUTPUT_PATH) -> None:
    rendered = json.dumps(result, indent=2, sort_keys=True, default=str)
    output_path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


def main() -> int:
    try:
        result = discover()
    except DiscoveryFailure as failure:
        result = failure_receipt(failure)
        _write_receipt(result)
        print(f"DISCOVERY_FAILED:{failure.code}")
        return 2

    _write_receipt(result)
    if result.get("eligible_count"):
        first = result["eligible_ledgers"][0]
        print("SELECTED_ELIGIBLE_LEDGER")
        print(f"ledger_id={first['ledger_id']}")
        print(f"version={first['version']}")
        print(f"review_content_hash={first['review_content_hash']}")
    else:
        print("NO_ELIGIBLE_LEDGER")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
