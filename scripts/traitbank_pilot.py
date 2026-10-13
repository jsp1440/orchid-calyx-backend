#!/usr/bin/env python3
"""TRAITBANK-PILOT-001: small, reproducible, real-data ingestion pilot.

Phases (run in order; every phase except ``fetch`` is offline):

    plan       print the manifest and every gate; touches nothing
    fetch      download ONE manifest source into a workdir outside the repo
               (refused without --approval-reference and --i-have-owner-approval)
    inspect    check a local file's layout; refuses an unrecognised header
    normalize  orchid rows only -> oc-traitbank-v1 batch + unmapped report
    ingest     into the pilot database only; dry-run unless --apply

Safety rails:

- Network: only ``fetch`` opens a connection, only to the manifest URL, with a
  byte cap, streaming sha256, and verification against a pinned checksum when
  the manifest has one. Nothing is downloaded by tests or by any other phase.
- Data never enters the repository: the workdir must be outside the git tree.
- Separate database: ``TRAITBANK_PILOT_DATABASE_URL`` is required, must name a
  database whose name contains ``pilot`` or ``test``, and must differ from
  ``TRAITBANK_DATABASE_URL`` and ``DATABASE_URL``.
- No production writes, no KG writes, no scheduling, no paid services.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import sys
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MANIFEST_PATH = ROOT / "docs" / "pilots" / "traitbank_pilot_001_manifest.json"
REQUIRED_COLUMNS = ("eol_pk", "predicate")
VALUE_COLUMNS = (
    "measurement",
    "normal_measurement",
    "value_uri",
    "object_term",
    "literal",
    "value",
)
NAME_COLUMNS = ("scientific_name", "page_id")
MAX_RECORDS = 5000


class PilotRefused(RuntimeError):
    pass


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("pilot") != "TRAITBANK-PILOT-001":
        raise PilotRefused("MANIFEST_NOT_TRAITBANK_PILOT_001")
    return manifest


def source(manifest: dict[str, Any], source_id: str) -> dict[str, Any]:
    found = next((s for s in manifest["sources"] if s["source_id"] == source_id), None)
    if found is None:
        raise PilotRefused(f"UNKNOWN_SOURCE:{source_id}")
    return found


def require_outside_repo(workdir: Path) -> Path:
    resolved = workdir.resolve()
    if resolved == ROOT or ROOT in resolved.parents:
        raise PilotRefused("WORKDIR_INSIDE_REPOSITORY")
    return resolved


def pilot_database_url(env: dict[str, str] | None = None) -> str:
    env = dict(os.environ if env is None else env)
    url = env.get("TRAITBANK_PILOT_DATABASE_URL", "").strip()
    if not url:
        raise PilotRefused("TRAITBANK_PILOT_DATABASE_URL_REQUIRED")
    for other in ("TRAITBANK_DATABASE_URL", "DATABASE_URL"):
        if env.get(other, "").strip() and env[other].strip() == url:
            raise PilotRefused(f"PILOT_DATABASE_MUST_DIFFER_FROM_{other}")
    name = urlsplit(url).path.lstrip("/").lower()
    if "pilot" not in name and "test" not in name:
        raise PilotRefused("PILOT_DATABASE_NAME_MUST_CONTAIN_PILOT_OR_TEST")
    return url


# ------------------------------------------------------------------- fetch
def fetch(
    manifest: dict[str, Any],
    source_id: str,
    workdir: Path,
    *,
    approval_reference: str,
    owner_approved: bool,
    opener: Any = None,
) -> dict[str, Any]:
    """Download one approved source. The only phase that touches the network."""
    if not owner_approved or not approval_reference.strip():
        raise PilotRefused("OWNER_APPROVAL_REQUIRED_BEFORE_DOWNLOAD")
    src = source(manifest, source_id)
    if src.get("status") != "approved_for_fetch":
        raise PilotRefused(f"SOURCE_NOT_APPROVED_FOR_FETCH:{src.get('status')}")
    target_dir = require_outside_repo(workdir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / src["filename"]
    max_bytes = int(src["max_bytes"])
    if opener is None:
        from urllib.request import urlopen as opener
    digest = hashlib.sha256()
    written = 0
    partial = target.with_suffix(target.suffix + ".partial")
    with opener(src["url"], timeout=60) as response, partial.open("wb") as out:
        while chunk := response.read(1024 * 1024):
            written += len(chunk)
            if written > max_bytes:
                out.close()
                partial.unlink(missing_ok=True)
                raise PilotRefused("DOWNLOAD_EXCEEDS_MAX_BYTES")
            digest.update(chunk)
            out.write(chunk)
    sha = digest.hexdigest()
    pinned = src.get("sha256")
    if pinned and pinned != sha:
        partial.unlink(missing_ok=True)
        raise PilotRefused("CHECKSUM_MISMATCH")
    partial.replace(target)
    return {
        "state": "FETCHED",
        "source_id": source_id,
        "path": str(target),
        "bytes": written,
        "sha256": sha,
        "checksum": "verified_against_manifest"
        if pinned
        else "recorded_first_fetch_pin_it_in_the_manifest",
        "approval_reference": approval_reference,
    }


# ------------------------------------------------------------- inspect / read
def _open_tables(path: Path) -> dict[str, list[dict[str, str]]]:
    """traits/pages tables from a zip archive or a single CSV/TSV file."""

    def read(text: str, name: str) -> list[dict[str, str]]:
        delimiter = "\t" if name.endswith(".tsv") else ","
        return list(csv.DictReader(io.StringIO(text), delimiter=delimiter))

    if zipfile.is_zipfile(path):
        tables: dict[str, list[dict[str, str]]] = {}
        with zipfile.ZipFile(path) as archive:
            for member in archive.namelist():
                base = Path(member).name.lower()
                if base in ("traits.csv", "pages.csv"):
                    tables[base.removesuffix(".csv")] = read(
                        archive.read(member).decode("utf-8"), base
                    )
        return tables
    return {"traits": read(path.read_text(encoding="utf-8"), path.name.lower())}


def inspect(path: Path) -> dict[str, Any]:
    tables = _open_tables(path)
    traits = tables.get("traits")
    if not traits:
        raise PilotRefused("NO_TRAITS_TABLE")
    header = set(traits[0])
    missing = [c for c in REQUIRED_COLUMNS if c not in header]
    if missing or not header & set(VALUE_COLUMNS) or not header & set(NAME_COLUMNS):
        raise PilotRefused(f"UNRECOGNISED_LAYOUT:{sorted(header)}")
    if "scientific_name" not in header and "pages" not in tables:
        raise PilotRefused("NO_TAXON_NAMES:traits has page_id only and no pages.csv")
    return {
        "state": "LAYOUT_RECOGNISED",
        "trait_rows": len(traits),
        "page_rows": len(tables.get("pages", [])),
        "columns": sorted(header),
        "value_columns_present": sorted(header & set(VALUE_COLUMNS)),
    }


def harvester_records(
    path: Path, *, max_records: int = MAX_RECORDS
) -> list[dict[str, Any]]:
    """Rows in ``TraitBankHarvester._normalize`` shape, names joined from pages.csv."""
    from harvesters.traitbank import TraitBankHarvester

    tables = _open_tables(path)
    names = {
        r.get("page_id"): r.get("canonical") or r.get("scientific_name")
        for r in tables.get("pages", [])
    }
    harvester = TraitBankHarvester()
    out = []
    for raw in tables["traits"]:
        if not raw.get("scientific_name") and names.get(raw.get("page_id")):
            raw = {**raw, "scientific_name": names[raw["page_id"]]}
        rec = harvester._normalize(raw, source_path=str(path))
        out.append(rec)
        if len(out) >= max_records:
            break
    return out


# ------------------------------------------------------------------ normalize
def normalize(
    path: Path,
    repo: Any,
    *,
    dataset_citation: str,
    dataset_license: str,
    max_records: int = MAX_RECORDS,
) -> dict[str, Any]:
    from app.traitbank.adapters import TraitIndex, from_traitbank_harvester

    records = harvester_records(path, max_records=max_records)
    result = from_traitbank_harvester(
        records,
        TraitIndex(repo.definitions()),
        repo.resolve_species,
        dataset_citation=dataset_citation,
        dataset_license=dataset_license,
    )
    reasons: dict[str, int] = {}
    for item in result.unmapped:
        reasons[item["reason"]] = reasons.get(item["reason"], 0) + 1
    return {
        "records_read": len(records),
        "assertions": len(result.batch.assertions) if result.batch else 0,
        "unmapped_by_reason": dict(sorted(reasons.items())),
        "batch": result.batch.model_dump(mode="json") if result.batch else None,
        "crosswalk": result.crosswalk,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="traitbank_pilot")
    sub = parser.add_subparsers(dest="phase", required=True)
    sub.add_parser("plan")
    f = sub.add_parser("fetch")
    f.add_argument("source_id")
    f.add_argument("--workdir", type=Path, required=True)
    f.add_argument("--approval-reference", default="")
    f.add_argument("--i-have-owner-approval", action="store_true")
    i = sub.add_parser("inspect")
    i.add_argument("path", type=Path)
    n = sub.add_parser("normalize")
    n.add_argument("path", type=Path)
    n.add_argument("--source-id", required=True)
    n.add_argument("--out", type=Path, required=True)
    n.add_argument("--max-records", type=int, default=MAX_RECORDS)
    g = sub.add_parser("ingest")
    g.add_argument("batch", type=Path)
    g.add_argument("--apply", action="store_true")
    g.add_argument("--ingested-by", default="")
    args = parser.parse_args(argv)
    manifest = load_manifest()
    try:
        if args.phase == "plan":
            print(json.dumps(manifest, indent=2))
            return 0
        if args.phase == "fetch":
            result = fetch(
                manifest,
                args.source_id,
                args.workdir,
                approval_reference=args.approval_reference,
                owner_approved=args.i_have_owner_approval,
            )
        elif args.phase == "inspect":
            result = inspect(args.path)
        else:
            from app.traitbank.repository import TraitBankRepository

            repo = TraitBankRepository(pilot_database_url())
            if args.phase == "normalize":
                src = source(manifest, args.source_id)
                require_outside_repo(args.out.parent)
                result = normalize(
                    args.path,
                    repo,
                    dataset_citation=src["citation"],
                    dataset_license=src["license"],
                    max_records=args.max_records,
                )
                args.out.write_text(json.dumps(result, indent=2, default=str))
                result = {
                    k: v for k, v in result.items() if k not in ("batch", "crosswalk")
                }
            else:
                from app.traitbank.models import TraitBankBatch

                if args.apply and not args.ingested_by.strip():
                    raise PilotRefused("APPLY_REQUIRES_INGESTED_BY")
                payload = json.loads(args.batch.read_text(encoding="utf-8"))
                result = repo.ingest(
                    TraitBankBatch.model_validate(payload["batch"]),
                    ingested_by=args.ingested_by or "dry-run",
                    dry_run=not args.apply,
                    crosswalk=payload.get("crosswalk"),
                )
    except PilotRefused as refused:
        print(json.dumps({"state": "REFUSED", "reason": str(refused)}))
        return 2
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
