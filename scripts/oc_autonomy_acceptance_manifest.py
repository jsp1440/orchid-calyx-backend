"""Build the Brain work manifest for a hosted, non-production autonomy acceptance.

Every work item is real, bounded, read-only work on the given workspace (a
branch checkout of this repository):

* one ``traitbank_batch_validator`` item per committed
  ``data/traitbank/*.json`` batch (pinned ``oc-traitbank-v1`` verdict), and
* ``repository_evidence_reader`` -> ``isolated_workspace_static_validator``
  items over a fixed, sorted set of in-repo Python modules (sha256-pinned
  parse and compile, never executed).

Items are chained (each depends on the previous one) so Brain dependency
validation is exercised, and every packet is built by the Brain's own
packet builders from ``--brain-checkout``. Nothing here submits anything; the
deployable worker's Brain pulse does that on its own schedule.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPOSITORY = "jsp1440/orchid-calyx-backend"
#: Fixed, reviewable source set for verification items (sorted, bounded).
SOURCE_GLOBS = ("app/traitbank/*.py", "app/calyx_orchestrator/program_*.py")
MAX_SOURCE_ITEMS = 16


def _branch(workspace: Path) -> str:
    head = (workspace / ".git" / "HEAD").read_text(encoding="ascii").strip()
    if not head.startswith("ref: refs/heads/"):
        raise SystemExit(
            "workspace must be a branch checkout (.git/HEAD names a branch)"
        )
    return head.removeprefix("ref: refs/heads/")


def _pinned(workspace: Path, relative: str) -> dict[str, str]:
    return {
        "path": relative,
        "sha256": hashlib.sha256((workspace / relative).read_bytes()).hexdigest(),
    }


def build_manifest(workspace: Path, brain_checkout: Path) -> dict:
    if str(brain_checkout) not in sys.path:
        sys.path.append(str(brain_checkout))
    from calyx_brain.reasoning_contracts import (
        CandidateKnowledge,
        build_verification_program,
    )
    from calyx_brain.traitbank_validation import build_traitbank_validation_program

    branch = _branch(workspace)
    work: list[dict] = []

    def add(work_id: str, packet: dict) -> None:
        work.append(
            {
                "work_id": work_id,
                "packet": packet,
                "depends_on": [work[-1]["work_id"]] if work else [],
            }
        )

    for path in sorted((workspace / "data" / "traitbank").glob("*.json")):
        relative = path.relative_to(workspace).as_posix()
        candidate = CandidateKnowledge(
            candidate_id=f"candidate:traitbank-batch:{relative}",
            subject_id=f"file:{relative}",
            predicate="has_valid_traitbank_contract",
            object_id="contract:oc-traitbank-v1",
            evidence_ids=(f"git:{REPOSITORY}:{relative}",),
            confidence=0.5,
        )
        add(
            f"traitbank-{path.stem}",
            build_traitbank_validation_program(
                candidate,
                repository=REPOSITORY,
                branch=branch,
                files=[_pinned(workspace, relative)],
            ),
        )
    sources = sorted(
        {
            p.relative_to(workspace).as_posix()
            for g in SOURCE_GLOBS
            for p in workspace.glob(g)
        }
    )[:MAX_SOURCE_ITEMS]
    for relative in sources:
        candidate = CandidateKnowledge(
            candidate_id=f"candidate:source:{relative}",
            subject_id=f"file:{relative}",
            predicate="has_verified_repository_source",
            object_id=f"git:{REPOSITORY}:{relative}",
            evidence_ids=(f"git:{REPOSITORY}:{relative}",),
            confidence=0.5,
        )
        add(
            f"source-{relative.replace('/', '-').removesuffix('.py')}",
            build_verification_program(
                candidate,
                repository=REPOSITORY,
                branch=branch,
                files=[_pinned(workspace, relative)],
            ),
        )
    return {"work": work}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--brain-checkout", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = build_manifest(args.workspace.resolve(), args.brain_checkout.resolve())
    args.output.write_text(
        json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps({"work_items": len(manifest["work"]), "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
