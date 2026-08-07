#!/usr/bin/env python3
"""Smoke-test a deployed read-only Orchid Continuum University backend.

Usage:
    python scripts/smoke_university_release.py https://backend.example.org/api

The base URL must be the API root immediately preceding `/learning`.
"""

from __future__ import annotations

import json
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

CHAPTER_ID = "BITB-CHAPTER-ORCHID-FLOWERING-001"
LAB_ID = "OCU-LAB-FAILURE-TO-BLOOM-001"


class SmokeFailure(RuntimeError):
    pass


def get_json(url: str) -> dict[str, Any]:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "OCU-release-smoke/1"})
    try:
        with urlopen(request, timeout=20) as response:
            if response.status != 200:
                raise SmokeFailure(f"{url}: expected 200, received {response.status}")
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise SmokeFailure(f"{url}: request failed: {exc}") from exc
    if not isinstance(payload, dict):
        raise SmokeFailure(f"{url}: JSON root must be an object")
    return payload


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: smoke_university_release.py <api-base-url>", file=sys.stderr)
        return 2

    api_base = sys.argv[1].rstrip("/")
    learning = f"{api_base}/learning"

    readiness = get_json(f"{learning}/release-readiness")
    require(readiness.get("release_contract") == "OCU-RELEASE-001", "unexpected release contract")
    require(readiness.get("read_only_ready") is True, "backend is not in safe read-only configuration")
    require(readiness.get("session_writes_enabled") is False, "session writes must remain disabled")
    require(readiness.get("publication_enabled") is False, "publication must remain disabled")
    require(readiness.get("candidate_knowledge_writes_enabled") is False, "Candidate Knowledge writes must remain disabled")
    require(readiness.get("calyx_model_calls_enabled") is False, "Calyx model calls must remain disabled")

    capability = get_json(f"{learning}/capabilities")
    require(capability.get("enabled") is True, "University capability is disabled")
    require(capability.get("session_writes_enabled") is False, "capability reports session writes enabled")

    catalog = get_json(f"{learning}/catalog")
    require(catalog.get("chapter", {}).get("id") == CHAPTER_ID, "catalog chapter contract mismatch")
    require(catalog.get("laboratory", {}).get("id") == LAB_ID, "catalog laboratory contract mismatch")

    chapter = get_json(f"{learning}/chapters/{CHAPTER_ID}")
    require(chapter.get("chapter_id") == CHAPTER_ID, "chapter response contract mismatch")

    laboratory = get_json(f"{learning}/laboratories/{LAB_ID}")
    require(laboratory.get("laboratory_id") == LAB_ID, "laboratory response contract mismatch")

    print("PASS: Orchid Continuum University read-only backend release contract")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SmokeFailure as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
