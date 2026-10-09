#!/usr/bin/env python3
"""Live API demonstration: authenticated Matrix contributor intake pathway.

Boots a real HTTP server (uvicorn, loopback only) carrying the contributor
intake router plus the existing Matrix session router, then drives the complete
pathway with real HTTP requests:

  POST /api/matrix-contributor/intake          (batch of photographs)
    -> filename -> staged image -> governed Matrix session mapping
  POST .../sessions/{id}/extractions           (machine extraction, review-required)
  GET  .../sessions/{id}/suggestions
  POST .../suggestions/{sid}/review            (expert accept / revise)
  POST .../sessions/{id}/evaluate              (existing Matrix scoring)
  POST .../sessions/{id}/evidence-record       (content-addressed, unverified)
  POST /api/matrix-contributor/intake (replay) (idempotency proof)

Everything runs in an isolated temporary workspace: file-backed governed
stores, a demo API key, no database, no paid providers, no network egress
beyond loopback. No migration is applied and no production system is touched.

Usage:
    python scripts/matrix_contributor_api_demo.py [--output demo-result.json]
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

API_KEY = "demo-contributor-key"
PHOTO_A = b"\xff\xd8\xff\xe0" + b"phragmipedium-kovachii-flower" * 8
PHOTO_B = b"\x89PNG\r\n\x1a\n" + b"unidentified-garden-orchid" * 8


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _prepare_workspace(workspace: Path) -> None:
    os.environ["CALYX_API_KEY"] = API_KEY
    os.environ["CALYX_MATRIX_SESSION_DIR"] = str(workspace / "sessions")
    os.environ["CALYX_MATRIX_REGISTRY_DIR"] = str(workspace / "registries")
    os.environ["CALYX_MATRIX_CONTRIBUTOR_INTAKE_DIR"] = str(workspace / "intake")
    os.environ.pop("CALYX_MATRIX_SESSION_DURABLE_ENABLED", None)
    os.environ.pop("DATABASE_URL", None)

    from runtime.matrix_identification import Candidate
    from runtime.matrix_identification_registry import (
        RegistryCharacter,
        create_registry_version,
    )

    create_registry_version(
        registry_id="phragmipedium-demo",
        version="1",
        title="Phragmipedium bounded diagnostic matrix",
        scope={"genus": "Phragmipedium"},
        characters=[
            RegistryCharacter("petal_color", "Petal color", weight=1),
            RegistryCharacter("pouch_shape", "Pouch shape", weight=2),
            RegistryCharacter(
                "leaf_length_cm", "Leaf length", value_type="numeric_range", weight=1
            ),
        ],
        candidates=[
            Candidate(
                "world-plants:phragmipedium-besseae",
                "Phragmipedium besseae",
                {
                    "petal_color": "red",
                    "pouch_shape": "slipper",
                    "leaf_length_cm": {"min": 20, "max": 35},
                },
                provenance={"source": "demo governed registry"},
            ),
            Candidate(
                "world-plants:phragmipedium-kovachii",
                "Phragmipedium kovachii",
                {
                    "petal_color": "pink",
                    "pouch_shape": "slipper",
                    "leaf_length_cm": {"min": 30, "max": 60},
                },
                provenance={"source": "demo governed registry"},
            ),
        ],
        provenance={"source": "offline api demonstration", "authoritative": "false"},
        actor="demo",
    )


def _build_app():
    from fastapi import FastAPI

    from app.routers.matrix_contributor import router as contributor_router
    from app.routers.matrix_identification_session import router as session_router

    app = FastAPI(title="matrix-contributor-live-intake-demo")
    app.include_router(contributor_router)
    app.include_router(session_router)
    return app


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", help="write the demo result JSON here")
    args = parser.parse_args()

    workspace = Path(tempfile.mkdtemp(prefix="matrix-contributor-api-demo-"))
    _prepare_workspace(workspace)

    import httpx
    import uvicorn

    app = _build_app()
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    if not server.started:
        print("server failed to start", file=sys.stderr)
        return 1

    base = f"http://127.0.0.1:{port}"
    headers = {"X-API-Key": API_KEY}
    result: dict = {"workspace": str(workspace), "base_url": base, "steps": {}}

    with httpx.Client(base_url=base, headers=headers, timeout=30.0) as http:
        print("== 0. Authentication boundary ==")
        unauthenticated = http.post(
            "/api/matrix-contributor/intake",
            json={
                "batch_id": "live-demo-unauth",
                "submissions": [
                    {
                        "original_filename": "probe.jpg",
                        "content_base64": _b64(PHOTO_A),
                        "contributor_display_name": "Probe",
                        "permission_grant": "cc-by",
                        "rights_holder_affirmed": True,
                    }
                ],
            },
            headers={"X-API-Key": "definitely-wrong"},
        )
        print(f"   unauthenticated intake -> HTTP {unauthenticated.status_code}")
        result["steps"]["unauthenticated_status"] = unauthenticated.status_code

        print("== 1. POST /api/matrix-contributor/intake (batch of 2 photographs) ==")
        intake = http.post(
            "/api/matrix-contributor/intake",
            json={
                "batch_id": "live-demo-batch-1",
                "open_sessions": True,
                "registry_id": "phragmipedium-demo",
                "registry_version": "1",
                "submissions": [
                    {
                        "original_filename": "kovachii_flower.jpg",
                        "content_base64": _b64(PHOTO_A),
                        "contributor_display_name": "R. Orchidist",
                        "permission_grant": "cc-by-nc",
                        "rights_holder_affirmed": True,
                        "taxon_certainty": "unknown",
                        "candidate_taxa": [{"name": "Phragmipedium kovachii"}],
                        "provenance": {"channel": "member-upload"},
                    },
                    {
                        "original_filename": "unidentified_garden.png",
                        "content_base64": _b64(PHOTO_B),
                        "contributor_display_name": "S. Gardener",
                        "permission_grant": "cc-by",
                        "rights_holder_affirmed": True,
                        "taxon_certainty": "unknown",
                    },
                ],
            },
        )
        intake.raise_for_status()
        manifest = intake.json()
        for item in manifest["filename_mapping"]:
            print(
                f"   {item['original_filename']} -> {item['status']} "
                f"submission={item['submission_id']} "
                f"session={item.get('session', {}).get('session_id') if item.get('session') else None}"
            )
        result["steps"]["intake"] = manifest
        entry = manifest["filename_mapping"][0]
        session_id = entry["session"]["session_id"]
        submission_id = entry["submission_id"]

        print("== 2. Machine extraction attached (review-required, nothing scored) ==")
        attached = http.post(
            f"/api/matrix-contributor/sessions/{session_id}/extractions",
            json={
                "submission_id": submission_id,
                "extractions": [
                    {
                        "character": "petal_color",
                        "value": "pink",
                        "machine_confidence": 0.81,
                        "extractor": "demo-vision-stub",
                        "extractor_version": "0.1.0",
                        "extraction_method": "offline_stub",
                    },
                    {
                        "character": "pouch_shape",
                        "value": "unknown-shape",
                        "machine_confidence": 0.33,
                        "extractor": "demo-vision-stub",
                        "extractor_version": "0.1.0",
                        "extraction_method": "offline_stub",
                    },
                ],
            },
        )
        attached.raise_for_status()
        states = {s["character"]: s["state"] for s in attached.json()["suggestions"]}
        print(f"   suggestion states: {states}")
        result["steps"]["attached_states"] = states

        scored_early = http.post(
            f"/api/matrix-contributor/sessions/{session_id}/evaluate",
            json={"limit": 5},
        )
        scored_early.raise_for_status()
        early_count = scored_early.json()["report"]["observation_count"]
        print(f"   scored observations before review: {early_count}")
        result["steps"]["observations_before_review"] = early_count

        print("== 3. Expert review over HTTP: accept petal_color, revise pouch_shape ==")
        suggestions = http.get(
            f"/api/matrix-contributor/sessions/{session_id}/suggestions"
        ).json()["suggestions"]
        for suggestion in suggestions:
            if suggestion["character"] == "petal_color":
                decision = {"decision": "accept", "certainty": "probable"}
            else:
                decision = {
                    "decision": "revise",
                    "revised_value": "slipper",
                    "certainty": "certain",
                    "comments": "pouch clearly slipper-shaped in image",
                }
            reviewed = http.post(
                f"/api/matrix-contributor/sessions/{session_id}"
                f"/suggestions/{suggestion['suggestion_id']}/review",
                json=decision,
            )
            reviewed.raise_for_status()
            print(f"   {suggestion['character']}: {decision['decision']} -> scored")
        result["steps"]["reviewed"] = True

        print("== 4. Existing Matrix scoring over reviewed observations ==")
        evaluated = http.post(
            f"/api/matrix-contributor/sessions/{session_id}/evaluate",
            json={"limit": 5},
        )
        evaluated.raise_for_status()
        report = evaluated.json()["report"]
        leader = report["candidates"][0]
        print(
            f"   leader (hypothesis): {leader['scientific_name']} "
            f"score={leader['score']} coverage={leader['coverage']}"
        )
        result["steps"]["report"] = report

        print("== 5. Content-addressed governed evidence record (unverified) ==")
        record_response = http.post(
            f"/api/matrix-contributor/sessions/{session_id}/evidence-record",
            json={
                "submission_id": submission_id,
                "source_assertions": [
                    {
                        "subject_id": "world-plants:phragmipedium-kovachii",
                        "character": "petal_color",
                        "value": "pink",
                        "source_ref": "demo:governed-source",
                    }
                ],
            },
        )
        record_response.raise_for_status()
        record = record_response.json()
        print(f"   verification_status: {record['verification_status']}")
        print(f"   checksum: {record['checksum_sha256']}")
        result["steps"]["evidence_record"] = record

        print("== 6. Batch replay idempotency ==")
        replay = http.post(
            "/api/matrix-contributor/intake",
            json={
                "batch_id": "live-demo-batch-1",
                "open_sessions": True,
                "registry_id": "phragmipedium-demo",
                "registry_version": "1",
                "submissions": [
                    {
                        "original_filename": "kovachii_flower.jpg",
                        "content_base64": _b64(PHOTO_A),
                        "contributor_display_name": "R. Orchidist",
                        "permission_grant": "cc-by-nc",
                        "rights_holder_affirmed": True,
                    }
                ],
            },
        )
        replay.raise_for_status()
        replay_manifest = replay.json()
        replay_session = replay_manifest["filename_mapping"][0]["session"]["session_id"]
        print(
            f"   idempotent_replay={replay_manifest['idempotent_replay']} "
            f"same_session={replay_session == session_id}"
        )
        result["steps"]["idempotent_replay"] = replay_manifest["idempotent_replay"]
        result["steps"]["replay_same_session"] = replay_session == session_id

        stored = http.get("/api/matrix-contributor/batches/live-demo-batch-1")
        result["steps"]["manifest_status"] = stored.status_code
        print(f"   persisted manifest GET -> HTTP {stored.status_code}")

    server.should_exit = True
    thread.join(timeout=5)

    checks = {
        "unauthenticated_blocked": result["steps"]["unauthenticated_status"] == 401,
        "nothing_scored_before_review": result["steps"]["observations_before_review"] == 0,
        "review_gate_opened_scoring": report["observation_count"] == 2,
        "evidence_unverified": record["verification_status"]
        == "unverified_candidate_evidence",
        "idempotent_replay": result["steps"]["idempotent_replay"] is True,
        "replay_same_session": result["steps"]["replay_same_session"] is True,
        "manifest_persisted": result["steps"]["manifest_status"] == 200,
    }
    result["checks"] = checks
    result["ok"] = all(checks.values())
    print("== checks ==")
    for name, passed in checks.items():
        print(f"   {'PASS' if passed else 'FAIL'} {name}")
    print(f"demo_ok={result['ok']}")

    if args.output:
        Path(args.output).write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"written to {args.output}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
