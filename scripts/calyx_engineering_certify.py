from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class CertificationConfig:
    base_url: str
    api_key: str
    pull_request_number: int
    paths: tuple[str, ...]
    objective: str
    ref: str


def _request(config: CertificationConfig, method: str, path: str, payload: dict | None = None) -> dict:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        f"{config.base_url.rstrip('/')}{path}",
        data=body,
        method=method,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-API-Key": config.api_key,
            "User-Agent": "calyx-engineering-certification",
        },
    )
    try:
        with urlopen(request, timeout=120) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        raise RuntimeError(f"HTTP_{exc.code}:{detail}") from exc
    except URLError as exc:
        raise RuntimeError("CERTIFICATION_ENDPOINT_UNREACHABLE") from exc


def run(config: CertificationConfig, *, apply_repair: bool) -> dict:
    status = _request(config, "GET", "/brain/engineering/status")
    inspection = _request(
        config,
        "POST",
        "/brain/engineering/inspect",
        {"paths": list(config.paths), "ref": config.ref},
    )
    failures = _request(
        config,
        "GET",
        f"/brain/engineering/pull-requests/{config.pull_request_number}/failures?limit=5",
    )
    evidence: dict = {
        "status": status,
        "inspection": {
            "ref": inspection.get("ref"),
            "file_count": inspection.get("file_count"),
            "paths": sorted((inspection.get("files") or {}).keys()),
        },
        "failures": failures,
        "repair_applied": False,
    }
    if apply_repair:
        repair = _request(
            config,
            "POST",
            f"/brain/engineering/pull-requests/{config.pull_request_number}/repair",
            {
                "paths": list(config.paths),
                "objective": config.objective,
                "attempt": 1,
                "approved": True,
            },
        )
        evidence["repair"] = repair
        evidence["repair_applied"] = True
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the controlled Calyx engineering certification checks.")
    parser.add_argument("--base-url", default=os.getenv("CALYX_CERTIFICATION_BASE_URL", ""))
    parser.add_argument("--api-key", default=os.getenv("CALYX_API_KEY", ""))
    parser.add_argument("--pull-request", type=int, required=True)
    parser.add_argument("--path", action="append", required=True)
    parser.add_argument(
        "--ref",
        default="main",
        help="Repository branch, tag, or commit to inspect. Use the certification PR head branch for disposable files.",
    )
    parser.add_argument(
        "--objective",
        default="Repair only the deterministic certification failure without changing workflows or unrelated files.",
    )
    parser.add_argument("--apply-repair", action="store_true")
    args = parser.parse_args()
    if not args.base_url or not args.api_key:
        parser.error("--base-url and --api-key (or matching environment variables) are required")
    config = CertificationConfig(
        base_url=args.base_url,
        api_key=args.api_key,
        pull_request_number=args.pull_request,
        paths=tuple(args.path),
        objective=args.objective,
        ref=args.ref,
    )
    try:
        evidence = run(config, apply_repair=args.apply_repair)
    except RuntimeError as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps({"status": "completed", "evidence": evidence}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
