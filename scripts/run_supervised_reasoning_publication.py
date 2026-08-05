"""Execute one explicitly owner-authorized Reasoning Ledger publication and emit evidence."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE_URL = os.environ.get("CALYX_BACKEND_URL", "https://orchid-calyx-backend.onrender.com").strip().rstrip("/")
ACCESS_CODE = os.environ.get("CALYX_OWNER_ACCESS_CODE", "")
LEDGER_ID = os.environ.get("CALYX_LEDGER_ID", "").strip()
EXPECTED_VERSION = os.environ.get("CALYX_EXPECTED_VERSION", "").strip()
EXPECTED_HASH = os.environ.get("CALYX_EXPECTED_REVIEW_CONTENT_HASH", "").strip().lower()
CONFIRMATION = os.environ.get("CALYX_PUBLICATION_CONFIRMATION", "").strip()
NOTE = os.environ.get("CALYX_PUBLICATION_NOTE", "Supervised CALYX production certification demonstration").strip()
EVIDENCE_PATH = Path(os.environ.get("CALYX_SUPERVISED_PUBLICATION_EVIDENCE_PATH", "calyx-supervised-publication-evidence.json"))
REQUIRED_CONFIRMATION = "PUBLISH ONE REVIEWED LEDGER"


def request(path: str, *, method: str = "GET", payload: dict | None = None, token: str = "") -> tuple[int, dict]:
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(f"{BASE_URL}{path}", data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=120) as response:
            body = response.read().decode()
            return response.status, json.loads(body) if body else {}
    except HTTPError as exc:
        body = exc.read().decode(errors="replace")[:2000]
        raise RuntimeError(f"{method} {path} -> HTTP {exc.code}: {body}") from exc


def main() -> int:
    try:
        if CONFIRMATION != REQUIRED_CONFIRMATION:
            raise ValueError("OWNER_CONFIRMATION_MISMATCH")
        if not ACCESS_CODE or not LEDGER_ID or not EXPECTED_VERSION or len(EXPECTED_HASH) != 64:
            raise ValueError("INCOMPLETE_SUPERVISED_PUBLICATION_INPUT")
        version = int(EXPECTED_VERSION)
        status, login = request(
            "/api/mission-control/owner/session-token",
            method="POST",
            payload={"access_code": ACCESS_CODE},
        )
        token = str(login.get("token") or "")
        if status != 200 or not token:
            raise RuntimeError("OWNER_SESSION_TOKEN_FAILED")
        _, before = request("/api/platform/knowledge-graph/persisted-audit", token=token)
        _, result = request(
            f"/api/reasoning-ledgers/{LEDGER_ID}/publish",
            method="POST",
            token=token,
            payload={
                "expected_version": version,
                "expected_review_content_hash": EXPECTED_HASH,
                "publication_note": NOTE,
            },
        )
        _, after = request("/api/platform/knowledge-graph/persisted-audit", token=token)
        artifact = result.get("artifact") or {}
        graph = artifact.get("graph") or {}
        outcome = str(graph.get("outcome") or "")
        if outcome not in {"PUBLISHED", "NO_OP_DUPLICATE"}:
            raise RuntimeError(f"UNEXPECTED_PUBLICATION_OUTCOME:{outcome or 'missing'}")
        evidence = {
            "schema_version": "1.0",
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "backend_url": BASE_URL,
            "ledger_id": LEDGER_ID,
            "expected_version": version,
            "expected_review_content_hash": EXPECTED_HASH,
            "owner_confirmation_verified": True,
            "automatic_publication": False,
            "single_publication_attempt": True,
            "before_audit": before,
            "publication_result": result,
            "after_audit": after,
            "outcome": outcome,
        }
        canonical = json.dumps(evidence, sort_keys=True, separators=(",", ":"), default=str)
        evidence["artifact_hash"] = sha256(canonical.encode()).hexdigest()
        EVIDENCE_PATH.write_text(json.dumps(evidence, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        print(json.dumps(evidence, indent=2, sort_keys=True, default=str))
        print("PASS supervised production publication demonstration completed")
        print("SAFE STOP: exactly one reviewed ledger publication was attempted")
        return 0
    except (ValueError, RuntimeError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"FAIL supervised_publication: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
