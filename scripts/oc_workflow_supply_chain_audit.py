from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

USES_RE = re.compile(r"^\s*(?:-\s*)?uses\s*:\s*([^\s@]+)@([^\s#]+)")
FULL_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")


@dataclass(frozen=True, slots=True)
class ActionReference:
    repository: str
    workflow_file: str
    line: int
    action: str
    ref: str
    classification: str
    immutable: bool


@dataclass(frozen=True, slots=True)
class RepositoryAudit:
    repository: str
    state: str
    references: tuple[ActionReference, ...]
    mutable_count: int | None


def classify_action(action: str) -> str:
    if action.startswith("./"):
        return "local"
    if action.startswith(("actions/", "github/")):
        return "first_party"
    return "third_party"


def audit_repository(repository: str, root: Path) -> RepositoryAudit:
    workflow_root = root / ".github" / "workflows"
    if not root.exists() or not workflow_root.exists():
        return RepositoryAudit(repository, "UNKNOWN", (), None)

    references: list[ActionReference] = []
    for workflow in sorted((*workflow_root.glob("*.yml"), *workflow_root.glob("*.yaml"))):
        for line_number, line in enumerate(
            workflow.read_text(encoding="utf-8").splitlines(), start=1
        ):
            match = USES_RE.match(line)
            if match is None:
                continue
            action, ref = match.groups()
            classification = classify_action(action)
            if classification == "local":
                continue
            references.append(
                ActionReference(
                    repository=repository,
                    workflow_file=str(workflow.relative_to(root)),
                    line=line_number,
                    action=action,
                    ref=ref,
                    classification=classification,
                    immutable=bool(FULL_SHA_RE.fullmatch(ref)),
                )
            )

    return RepositoryAudit(
        repository=repository,
        state="AVAILABLE",
        references=tuple(references),
        mutable_count=sum(not reference.immutable for reference in references),
    )


def remediation_manifest(audits: tuple[RepositoryAudit, ...]) -> dict[str, object]:
    unknown = any(audit.state != "AVAILABLE" for audit in audits)
    mutable = [
        asdict(reference)
        for audit in audits
        for reference in audit.references
        if not reference.immutable
    ]
    return {
        "schema_version": "oc.workflow-supply-chain-audit.v1",
        "repositories": [
            {
                "repository": audit.repository,
                "state": audit.state,
                "reference_count": len(audit.references),
                "mutable_count": audit.mutable_count,
            }
            for audit in audits
        ],
        "mutable_remote_references": mutable,
        "remediation_state": (
            "UNKNOWN"
            if unknown
            else "REVIEW_REQUIRED"
            if mutable
            else "NO_MUTABLE_REFS_FOUND"
        ),
        "workflow_rewrites_performed": False,
    }


def audit_exit_code(audits: tuple[RepositoryAudit, ...]) -> int:
    return int(
        any(
            audit.state != "AVAILABLE" or bool(audit.mutable_count)
            for audit in audits
        )
    )


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("roots", nargs="+", help="NAME=PATH repository roots")
    args = parser.parse_args()
    audits = []
    for item in args.roots:
        name, separator, path = item.partition("=")
        if not separator:
            parser.error("roots must use NAME=PATH")
        audits.append(audit_repository(name, Path(path)))

    audited = tuple(audits)
    manifest = remediation_manifest(audited)
    print(json.dumps(manifest, sort_keys=True, indent=2))
    return audit_exit_code(audited)


if __name__ == "__main__":
    raise SystemExit(main())
