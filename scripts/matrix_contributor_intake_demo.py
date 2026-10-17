#!/usr/bin/env python3
"""End-to-end offline demo: governed Matrix contributor intake pathway.

Pipeline demonstrated (fully offline; extractor and provider are stubs and no
Firecrawl credits are spent):

  contributor image batch intake (attribution/permission/provenance preserved)
    -> governed Matrix identification session bound to a registry version
    -> machine character extraction attached as review-required suggestions
    -> expert review (accept / revise / reject)
    -> deterministic candidate re-ranking
    -> reuse-before-pay morphology evidence plan + budget-guarded source fetch
    -> source comparison against existing governed assertions
    -> content-addressed governed Matrix evidence record

Usage:
    python scripts/matrix_contributor_intake_demo.py [--output evidence.json]
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.federation.morphology_evidence import (  # noqa: E402
    InMemoryAcquisitionLedger,
    MorphologyEvidenceService,
    SourcePolicy,
    plan_evidence_acquisition,
)
from runtime.contributor_image_intake import intake_contributor_batch  # noqa: E402
from runtime.matrix_contributor_bridge import (  # noqa: E402
    attach_contributor_extractions,
    build_contributor_evidence_record,
    review_contributor_suggestion,
)
from runtime.matrix_identification import Candidate  # noqa: E402
from runtime.matrix_identification_registry import (  # noqa: E402
    RegistryCharacter,
    create_registry_version,
)
from runtime.matrix_identification_session import create_session, get_session  # noqa: E402

POWO_PAGE = (
    "Phragmipedium kovachii has large pink to rose-purple petals. "
    "The pouch is slipper-shaped. "
    "Leaves reach 30 to 60 cm in length."
)


def _stub_extractor(*, url: str, taxon_name: str) -> str:
    return POWO_PAGE


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", help="write the governed evidence record JSON here")
    args = parser.parse_args()

    workspace = Path(tempfile.mkdtemp(prefix="matrix-contributor-demo-"))
    registry_root = workspace / "registries"
    session_root = workspace / "sessions"

    print("== 1. Create bounded governed registry (Phragmipedium demo) ==")
    receipt = create_registry_version(
        registry_id="phragmipedium-demo",
        version="1",
        title="Phragmipedium bounded diagnostic matrix",
        scope={"genus": "Phragmipedium"},
        characters=[
            RegistryCharacter("petal_color", "Petal color", weight=1),
            RegistryCharacter("pouch_shape", "Pouch shape", weight=2),
            RegistryCharacter("leaf_length_cm", "Leaf length", value_type="numeric_range", weight=1),
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
        provenance={"source": "offline demonstration", "authoritative": "false"},
        actor="demo",
        root=registry_root,
    )
    print(f"   registry checksum: {receipt['record']['checksum_sha256'][:16]}...")

    print("== 2. Contributor image batch intake (3 submissions) ==")
    intake = intake_contributor_batch(
        [
            {
                "submission_id": "demo-sub-1",
                "contributor_id": "member-7",
                "contributor_display_name": "R. Orchidist",
                "permission_grant": "cc-by-nc",
                "rights_holder_affirmed": True,
                "original_object_ref": "objects/originals/demo-sub-1.jpg",
                "content_sha256": "d" * 64,
                "mime_type": "image/jpeg",
                "taxon_name": None,
                "taxon_certainty": "unknown",
                "candidate_taxa": [{"name": "Phragmipedium kovachii"}],
                "provenance": {"channel": "member-upload", "captured_at": "2026-10-01"},
            },
            {  # exact re-submission of the same photograph -> deduplicated
                "submission_id": "demo-sub-1-duplicate",
                "contributor_id": "member-7",
                "contributor_display_name": "R. Orchidist",
                "permission_grant": "cc-by-nc",
                "rights_holder_affirmed": True,
                "original_object_ref": "objects/originals/demo-sub-1.jpg",
                "content_sha256": "d" * 64,
                "mime_type": "image/jpeg",
                "taxon_certainty": "unknown",
            },
            {  # missing permission grant -> rejected
                "submission_id": "demo-sub-2",
                "contributor_id": "member-9",
                "contributor_display_name": "S. Gardener",
                "rights_holder_affirmed": True,
                "original_object_ref": "objects/originals/demo-sub-2.jpg",
                "content_sha256": "e" * 64,
                "mime_type": "image/jpeg",
                "taxon_certainty": "unknown",
            },
        ],
        batch_id="demo-batch-1",
    )
    summary = intake.summary()
    print(f"   {json.dumps(summary, sort_keys=True)}")
    staged = intake.staged[0]

    print("== 3. Open governed Matrix session for the staged image ==")
    session = create_session(
        registry_id="phragmipedium-demo",
        version="1",
        actor="member-7",
        metadata={"contributor_submission_id": staged.submission_id},
        root=session_root,
        registry_root=registry_root,
    )
    print(f"   session {session['session_id']} (revision {session['revision']})")

    print("== 4. Machine extraction attached as review-required suggestions ==")
    attached = attach_contributor_extractions(
        session["session_id"],
        staged,
        [
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
        access_actor="member-7",
        root=session_root,
        registry_root=registry_root,
    )
    print(f"   {attached['added']} suggestions staged; none scored yet")

    print("== 5. Expert review: accept petal_color, revise pouch_shape ==")
    current = get_session(session["session_id"], root=session_root)
    for suggestion in current["contributor_suggestions"]:
        if suggestion["character"] == "petal_color":
            review_contributor_suggestion(
                session["session_id"], suggestion["suggestion_id"],
                decision="accept", reviewer="expert-demo", certainty="probable",
                access_actor="member-7", root=session_root, registry_root=registry_root,
            )
        elif suggestion["character"] == "pouch_shape":
            review_contributor_suggestion(
                session["session_id"], suggestion["suggestion_id"],
                decision="revise", reviewer="expert-demo", revised_value="slipper",
                certainty="certain", comments="pouch clearly slipper-shaped in image",
                access_actor="member-7", root=session_root, registry_root=registry_root,
            )

    print("== 6. Reuse-before-pay morphology evidence plan + budget-guarded fetch ==")
    existing_coverage = {"pouch_shape": [{"source_ref": "kg:traits:demo-1"}]}
    plan = plan_evidence_acquisition(
        ["petal_color", "pouch_shape", "leaf_length_cm"], existing_coverage
    )
    print(f"   skip provider calls for: {plan['skip_provider_call']}")
    print(f"   acquisition candidates: {plan['needs_acquisition']}")
    ledger = InMemoryAcquisitionLedger()
    service = MorphologyEvidenceService(
        ledger,
        extractor=_stub_extractor,
        policies={
            "powo": SourcePolicy(
                source_id="powo",
                root_url="https://powo.science.kew.org/",
                terms_reviewed=True,
                robots_compliant=True,
                attribution="Plants of the World Online, Royal Botanic Gardens, Kew",
            )
        },
        max_credits=2,
    )
    fetch = service.extract_morphology(
        consumer_module="matrix",
        source_id="powo",
        url="https://powo.science.kew.org/taxon/demo-kovachii",
        taxon_name="Phragmipedium kovachii",
        characters=plan["needs_acquisition"],
    )
    repeat = service.extract_morphology(
        consumer_module="matrix",
        source_id="powo",
        url="https://powo.science.kew.org/taxon/demo-kovachii",
        taxon_name="Phragmipedium kovachii",
        characters=plan["needs_acquisition"],
    )
    print(f"   first: {fetch['status']} ({len(fetch['items'])} excerpts), repeat: {repeat['status']}")
    print(f"   ledger: {json.dumps(ledger.metrics(), sort_keys=True)}")
    source_assertions = [
        {
            "subject_id": "world-plants:phragmipedium-kovachii",
            "character": "petal_color",
            "value": "pink",
            "source_ref": "firecrawl_scrape:powo:demo-kovachii",
            "citation": fetch["items"][0]["attribution"] if fetch["items"] else "POWO",
        }
    ]

    print("== 7. Build governed, content-addressed Matrix evidence record ==")
    record = build_contributor_evidence_record(
        session["session_id"],
        staged,
        source_assertions=source_assertions,
        access_actor="member-7",
        root=session_root,
        registry_root=registry_root,
    )
    leader = record["candidate_ranking"]["candidates"][0]
    print(f"   leading candidate (hypothesis): {leader['scientific_name']} "
          f"score={leader['score']} coverage={leader['coverage']}")
    print(f"   verification_status: {record['verification_status']}")
    print(f"   checksum: {record['checksum_sha256']}")

    if args.output:
        Path(args.output).write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"   written to {args.output}")
    else:
        print(json.dumps(record, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
