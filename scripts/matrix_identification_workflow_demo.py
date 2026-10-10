#!/usr/bin/env python3
"""Live API demonstration: governed Matrix identification workflow (Phase 3).

Boots a real HTTP server (uvicorn, loopback only) and drives the complete
identification pathway with real HTTP requests:

  image submission -> character extraction (fixture extractor, explicitly
    labeled; plus an explicit manual-character fallback) -> candidate
    identification with evidence explanation -> expert review -> accepted
    observations -> updated deterministic scoring -> durable identification
    report with taxonomic resolution, synonym reconciliation, ambiguity,
    uncertainty, and contributor-image provenance.

Every printed step is labeled AUTOMATED or HUMAN so the demonstration never
blurs which stages are genuinely automated. Image-based identification is NOT
claimed: the fixture extractor is a deterministic stand-in and its output
scores only after human review. No paid providers, no database, no network
egress beyond loopback, no migrations.

Usage:
    python scripts/matrix_identification_workflow_demo.py [--output result.json]
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

API_KEY = "demo-identification-key"
PHOTO = b"\xff\xd8\xff\xe0" + b"phragmipedium-kovachii-fixture" * 8

SYNONYM_ENTRIES = [
    {
        "canonical_taxon_id": "world-plants:phragmipedium-kovachii",
        "accepted_name": "Phragmipedium kovachii",
        "synonyms": ["Phragmipedium peruvianum"],
    }
]


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
        registry_id="phragmipedium-id-demo",
        version="1",
        title="Phragmipedium identification demo matrix",
        scope={"genus": "Phragmipedium"},
        characters=[
            RegistryCharacter("petal_color", "Petal color", weight=1),
            RegistryCharacter("pouch_shape", "Pouch shape", weight=2),
            RegistryCharacter(
                "leaf_length_cm", "Leaf length", value_type="numeric_range", weight=1
            ),
            RegistryCharacter("labellum_shape", "Labellum shape", weight=1),
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
            Candidate(
                "unreconciled:peruvianum-row",
                "Phragmipedium peruvianum",
                {
                    "petal_color": "pink",
                    "pouch_shape": "slipper",
                    "leaf_length_cm": {"min": 30, "max": 60},
                },
                provenance={"source": "demo governed registry"},
            ),
        ],
        provenance={"source": "offline identification demo", "authoritative": "false"},
        actor="demo",
    )


def _build_app():
    from fastapi import FastAPI

    from app.routers.matrix_contributor import router as contributor_router

    app = FastAPI(title="matrix-identification-workflow-demo")
    app.include_router(contributor_router)
    return app


def _serve(app, port: int):
    import uvicorn

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    return server, thread


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", help="write the demo result JSON here")
    args = parser.parse_args()

    workspace = Path(tempfile.mkdtemp(prefix="matrix-identification-demo-"))
    _prepare_workspace(workspace)

    import httpx

    port = _free_port()
    server, thread = _serve(_build_app(), port)
    if not server.started:
        print("server failed to start", file=sys.stderr)
        return 1

    base = f"http://127.0.0.1:{port}"
    headers = {"X-API-Key": API_KEY}
    result: dict = {"workspace": str(workspace), "base_url": base, "steps": {}}

    with httpx.Client(base_url=base, headers=headers, timeout=30.0) as http:
        print("== 0. Authentication boundary [AUTOMATED check] ==")
        # Dedicated headerless client: the demo client's default headers carry
        # the API key, so the unauthenticated probe must bypass them.
        with httpx.Client(base_url=base, timeout=30.0) as anonymous:
            unauthenticated = anonymous.post(
                "/api/matrix-contributor/sessions/none/identification", json={}
            )
        print(f"   unauthenticated identification -> HTTP {unauthenticated.status_code}")
        result["steps"]["unauthenticated_status"] = unauthenticated.status_code

        print("== 1. Contributor image submission [AUTOMATED] ==")
        intake = http.post(
            "/api/matrix-contributor/intake",
            json={
                "batch_id": "id-demo-batch-1",
                "open_sessions": True,
                "registry_id": "phragmipedium-id-demo",
                "registry_version": "1",
                "submissions": [
                    {
                        "original_filename": "kovachii_flower.jpg",
                        "content_base64": _b64(PHOTO),
                        "contributor_display_name": "R. Orchidist",
                        "permission_grant": "cc-by-nc",
                        "rights_holder_affirmed": True,
                        "taxon_certainty": "unknown",
                        "provenance": {"channel": "member-upload"},
                    }
                ],
            },
        )
        intake.raise_for_status()
        entry = intake.json()["filename_mapping"][0]
        session_id = entry["session"]["session_id"]
        submission_id = entry["submission_id"]
        print(
            f"   {entry['original_filename']} -> session {session_id} "
            f"(attribution: {entry['attribution_line']})"
        )
        result["steps"]["intake"] = entry

        print("== 2. Character extraction [AUTOMATED fixture + MANUAL fallback] ==")
        print("   NOTE: fixture extractor is a deterministic stand-in; no")
        print("   image-based identification is claimed. Manual fallback uses")
        print("   contributor-supplied characters through the same review gate.")
        attached = http.post(
            f"/api/matrix-contributor/sessions/{session_id}/extractions",
            json={
                "submission_id": submission_id,
                "extractions": [
                    {
                        "character": "petal_color",
                        "value": "pink",
                        "machine_confidence": 0.81,
                        "extractor": "fixture-extractor",
                        "extractor_version": "0.1.0",
                        "extraction_method": "deterministic_fixture",
                        "limitations": ["fixture stand-in, not a vision model"],
                    },
                    {
                        "character": "leaf_length_cm",
                        "value": 25,
                        "machine_confidence": None,
                        "extractor": "manual-contributor",
                        "extractor_version": None,
                        "extraction_method": "manual_fallback_contributor_supplied",
                    },
                ],
            },
        )
        attached.raise_for_status()
        states = {s["character"]: s["state"] for s in attached.json()["suggestions"]}
        print(f"   suggestions (review-required): {states}")
        result["steps"]["attached_states"] = states

        scored_early = http.post(
            f"/api/matrix-contributor/sessions/{session_id}/evaluate",
            json={"limit": 5},
        )
        early = scored_early.json()["report"]["observation_count"]
        print(f"   scored observations before review: {early} (gate holds)")
        result["steps"]["observations_before_review"] = early

        print("== 3. Expert review [HUMAN] ==")
        suggestions = http.get(
            f"/api/matrix-contributor/sessions/{session_id}/suggestions"
        ).json()["suggestions"]
        for suggestion in suggestions:
            certainty = "probable" if suggestion["character"] == "petal_color" else "certain"
            reviewed = http.post(
                f"/api/matrix-contributor/sessions/{session_id}"
                f"/suggestions/{suggestion['suggestion_id']}/review",
                json={"decision": "accept", "certainty": certainty},
            )
            reviewed.raise_for_status()
            print(f"   reviewer accepted {suggestion['character']} ({certainty})")
        result["steps"]["reviewed"] = True

        print("== 4. Candidate identification with evidence explanation [AUTOMATED] ==")
        identification = http.post(
            f"/api/matrix-contributor/sessions/{session_id}/identification",
            json={"limit": 5, "synonym_entries": SYNONYM_ENTRIES},
        )
        identification.raise_for_status()
        report = identification.json()
        for candidate in report["ranked_candidates"]:
            resolution = candidate["taxonomic_resolution"]
            print(
                f"   {candidate['scientific_name']}: score={candidate['score']} "
                f"coverage={candidate['coverage']} "
                f"resolution={resolution['resolution_state']}"
                + (
                    f" (accepted: {resolution['accepted_name']})"
                    if resolution["resolution_state"] == "resolved_synonym"
                    else ""
                )
            )
        result["steps"]["identification"] = report

        ambiguity = report["ambiguity"]
        print(
            f"   ambiguity: {ambiguity['is_ambiguous']} "
            f"(leaders: {[l['scientific_name'] for l in ambiguity['leader_group']]})"
        )
        print(
            "   unobserved characters: "
            f"{[c['character'] for c in report['unobserved_characters']]}"
        )
        collapsed = [g for g in report["synonym_groups"] if g["collapsed"]]
        print(
            "   synonym reconciliation: "
            + (
                f"{collapsed[0]['aliases']} -> {collapsed[0]['accepted_name']}"
                if collapsed
                else "none"
            )
        )
        leader = report["ranked_candidates"][0]
        link = leader["supporting_characters"][0]["evidence_links"][0]
        print(
            f"   provenance: {link['attribution_line']} "
            f"sha256={str(link['content_sha256'])[:16]}... "
            f"ref={link['original_object_ref']}"
        )

        print("== 5. Repeat request idempotency + restart persistence [AUTOMATED] ==")
        repeat = http.post(
            f"/api/matrix-contributor/sessions/{session_id}/identification",
            json={"limit": 5, "synonym_entries": SYNONYM_ENTRIES},
        )
        repeat.raise_for_status()
        same_checksum = repeat.json()["checksum_sha256"] == report["checksum_sha256"]
        print(f"   repeat checksum identical: {same_checksum}")
        result["steps"]["repeat_same_checksum"] = same_checksum

    server.should_exit = True
    thread.join(timeout=5)

    # Simulated restart: brand-new server over the same governed workspace.
    port2 = _free_port()
    server2, thread2 = _serve(_build_app(), port2)
    with httpx.Client(
        base_url=f"http://127.0.0.1:{port2}", headers=headers, timeout=30.0
    ) as http2:
        after = http2.post(
            f"/api/matrix-contributor/sessions/{session_id}/identification",
            json={"limit": 5, "synonym_entries": SYNONYM_ENTRIES},
        )
        after.raise_for_status()
        restart_same = after.json()["checksum_sha256"] == report["checksum_sha256"]
        print(f"   post-restart checksum identical: {restart_same}")
        result["steps"]["restart_same_checksum"] = restart_same
    server2.should_exit = True
    thread2.join(timeout=5)

    print("== 6. Stage labeling (honest automation boundary) ==")
    for stage in report["automation_stages"]:
        print(f"   {stage['stage']}: {stage['actor']}")

    checks = {
        "unauthenticated_blocked": result["steps"]["unauthenticated_status"] == 401,
        "nothing_scored_before_review": result["steps"]["observations_before_review"] == 0,
        "reviewed_observations_scored": report["observation_count"] == 2,
        "leader_is_kovachii_hypothesis": leader["scientific_name"]
        == "Phragmipedium kovachii",
        "ambiguity_detected": report["ambiguity"]["is_ambiguous"] is True,
        "synonym_collapsed": bool(collapsed),
        "unobserved_character_listed": any(
            c["character"] == "labellum_shape"
            for c in report["unobserved_characters"]
        ),
        "provenance_linked": link["attribution_line"] == "R. Orchidist (CC-BY-NC)",
        "limitations_honest": any(
            "not a taxonomic determination" in item for item in report["limitations"]
        ),
        "repeat_idempotent": result["steps"]["repeat_same_checksum"] is True,
        "restart_persistent": result["steps"]["restart_same_checksum"] is True,
    }
    result["checks"] = checks
    result["ok"] = all(checks.values())
    print("== checks ==")
    for name, passed in checks.items():
        print(f"   {'PASS' if passed else 'FAIL'} {name}")
    print(f"identification_demo_ok={result['ok']}")

    if args.output:
        Path(args.output).write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"written to {args.output}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
