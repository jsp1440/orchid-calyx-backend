"""Versioned, leakage-safe training-data preparation and evaluation.

:func:`build_dataset_manifest` turns reference-image records into a
reproducible train / validation / test manifest:

* only training-label-eligible records are used (expert-verified identity,
  accepted taxon, taxonomy version, accessible image, allowed license);
* duplicate groups are resolved first and every image of one specimen or
  observation lands in the same split (specimen-grouped partitioning);
* split assignment is a deterministic hash of (seed, group key), stratified
  per taxon so small taxa still reach the test split;
* a set of taxa can be held out entirely as an open-set / out-of-distribution
  test of "unknown taxon" behaviour;
* the manifest is pinned to one taxonomy version and carries a content hash
  so any change to the data produces a new version.

:func:`verify_no_leakage` re-checks a manifest independently.
:func:`evaluate_predictions` scores supplied predictions at genus and
species level separately, with abstention, open-set and calibration
metrics. It evaluates predictions; it does not train anything.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from runtime.reference_images import (
    ReferenceImageRecord,
    group_duplicates,
    normalize_image_url,
)

MANIFEST_SCHEMA_VERSION = "oc-image-dataset-manifest/v1"
SPLITS = ("train", "validation", "test")


def _bucket(seed: str, key: str) -> float:
    digest = hashlib.sha256(f"{seed}|{key}".encode()).hexdigest()
    return int(digest[:12], 16) / float(16**12)


def build_dataset_manifest(
    records: Iterable[ReferenceImageRecord],
    *,
    taxonomy_version: str,
    seed: str = "oc-image-dataset",
    ratios: tuple[float, float, float] = (0.7, 0.15, 0.15),
    min_groups_per_taxon: int = 1,
    open_set_taxon_ids: Iterable[str] = (),
    dataset_name: str = "oc-reference-images",
) -> dict[str, Any]:
    if abs(sum(ratios) - 1.0) > 1e-9 or any(r < 0 for r in ratios):
        raise ValueError("ratios_must_sum_to_one")
    open_set = set(open_set_taxon_ids)
    items = group_duplicates(list(records))
    excluded: dict[str, int] = defaultdict(int)
    eligible: list[ReferenceImageRecord] = []
    for rec in items:
        ok, reasons = rec.training_label_eligibility()
        if not ok:
            for r in reasons:
                excluded[r] += 1
            continue
        if rec.taxonomy_version != taxonomy_version:
            excluded["taxonomy_version_mismatch"] += 1
            continue
        eligible.append(rec)

    # A duplicate group may span several specimen keys (e.g. one photo posted
    # under two occurrences). Merge such keys so the group is indivisible.
    parent: dict[str, str] = {}

    def find(k: str) -> str:
        parent.setdefault(k, k)
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    for rec in eligible:
        find(rec.specimen_group_key)
        if rec.duplicate_group_id:
            a, b = find(rec.specimen_group_key), find(f"dup:{rec.duplicate_group_id}")
            if a != b:
                parent[b] = a

    merged: dict[str, list[ReferenceImageRecord]] = defaultdict(list)
    for rec in eligible:
        merged[find(rec.specimen_group_key)].append(rec)
    # Name each group by its smallest member key so the manifest does not
    # depend on input order.
    groups: dict[str, list[ReferenceImageRecord]] = {
        min(r.specimen_group_key for r in recs): recs for recs in merged.values()
    }

    # A group whose images disagree on taxon is unusable as a label.
    conflicting = {
        k for k, recs in groups.items() if len({r.accepted_taxon_id for r in recs}) > 1
    }
    for k in conflicting:
        excluded["specimen_group_taxon_conflict"] += len(groups[k])
        del groups[k]

    by_taxon: dict[str, list[str]] = defaultdict(list)
    for key, recs in groups.items():
        by_taxon[recs[0].accepted_taxon_id].append(key)

    assignment: dict[str, str] = {}
    for taxon_id, keys in sorted(by_taxon.items()):
        if taxon_id in open_set:
            for k in keys:
                assignment[k] = "open_set_test"
            continue
        if len(keys) < min_groups_per_taxon:
            for k in keys:
                excluded["taxon_below_min_groups"] += len(groups[k])
            continue
        ordered = sorted(keys, key=lambda k: _bucket(seed, k))
        n = len(ordered)
        if n == 1:
            assignment[ordered[0]] = "train"
            continue
        n_test = max(1, round(n * ratios[2])) if n >= 3 else 0
        n_val = (
            max(1, round(n * ratios[1]))
            if n >= 3
            else (1 if n == 2 and ratios[1] > 0 else 0)
        )
        n_test = min(n_test, n - 1)
        n_val = min(n_val, n - 1 - n_test)
        for i, k in enumerate(ordered):
            assignment[k] = (
                "test"
                if i < n_test
                else ("validation" if i < n_test + n_val else "train")
            )

    entries = []
    for key, split in sorted(assignment.items()):
        for rec in sorted(groups[key], key=lambda r: r.image_id):
            entries.append(
                {
                    "image_id": rec.image_id,
                    "split": split,
                    "group_key": key,
                    "accepted_taxon_id": rec.accepted_taxon_id,
                    "accepted_name": rec.accepted_name,
                    "verification_status": rec.verification_status,
                    "verifier": rec.verifier,
                    "source": rec.source,
                    "source_record_id": rec.source_record_id,
                    "license": rec.license,
                    "image_url": rec.image_url,
                    "storage_ref": rec.storage_ref,
                    "content_sha256": rec.content_sha256,
                    "duplicate_group_id": rec.duplicate_group_id,
                    "organ": rec.organ,
                    "viewpoint": rec.viewpoint,
                }
            )
    content_hash = hashlib.sha256(
        json.dumps(
            {
                "taxonomy_version": taxonomy_version,
                "seed": seed,
                "ratios": ratios,
                "entries": entries,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    split_counts = {
        s: sum(1 for e in entries if e["split"] == s)
        for s in (*SPLITS, "open_set_test")
    }
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "dataset_name": dataset_name,
        "dataset_version": f"{dataset_name}@{content_hash[:12]}",
        "content_sha256": content_hash,
        "taxonomy_version": taxonomy_version,
        "seed": seed,
        "ratios": list(ratios),
        "label_policy": "expert_verified_only",
        "grouping": "specimen_or_occurrence_then_duplicate_group",
        "open_set_taxon_ids": sorted(open_set),
        "entries": entries,
        "split_counts": split_counts,
        "taxa_per_split": {
            s: len({e["accepted_taxon_id"] for e in entries if e["split"] == s})
            for s in (*SPLITS, "open_set_test")
        },
        "excluded": dict(sorted(excluded.items())),
        "trained_model": None,
    }
    manifest["leakage_check"] = verify_no_leakage(manifest)
    return manifest


def verify_no_leakage(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Independently verify that no specimen, duplicate, hash or URL crosses splits."""
    seen: dict[tuple[str, str], set[str]] = defaultdict(set)
    for e in manifest["entries"]:
        split = e["split"]
        seen[("group", e["group_key"])].add(split)
        if e.get("duplicate_group_id"):
            seen[("duplicate", e["duplicate_group_id"])].add(split)
        if e.get("content_sha256"):
            seen[("sha256", e["content_sha256"].lower())].add(split)
        url = normalize_image_url(e.get("image_url"))
        if url:
            seen[("url", url)].add(split)
        seen[("image", e["image_id"])].add(split)
    violations = [
        {"kind": k, "key": v, "splits": sorted(s)}
        for (k, v), s in seen.items()
        if len(s) > 1
    ]
    open_set = set(manifest.get("open_set_taxon_ids", []))
    for e in manifest["entries"]:
        if e["accepted_taxon_id"] in open_set and e["split"] != "open_set_test":
            violations.append(
                {
                    "kind": "open_set_taxon_in_closed_split",
                    "key": e["image_id"],
                    "splits": [e["split"]],
                }
            )
    versions = {manifest.get("taxonomy_version")}
    return {
        "passed": not violations,
        "violations": violations,
        "taxonomy_versions": sorted(v for v in versions if v),
    }


def _ece(
    confidences: Sequence[float], correct: Sequence[bool], bins: int = 10
) -> float | None:
    if not confidences:
        return None
    total = len(confidences)
    ece = 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        idx = [
            i
            for i, c in enumerate(confidences)
            if (lo < c <= hi) or (b == 0 and c == 0)
        ]
        if not idx:
            continue
        acc = sum(correct[i] for i in idx) / len(idx)
        conf = sum(confidences[i] for i in idx) / len(idx)
        ece += len(idx) / total * abs(acc - conf)
    return round(ece, 6)


def reliability_bins(
    confidences: Sequence[float], correct: Sequence[bool], bins: int = 10
) -> list[tuple[float, float]]:
    """(upper_bound, accuracy) bins suitable for ``CalibrationTable``."""
    out = []
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        idx = [
            i for i, c in enumerate(confidences) if lo < c <= hi or (b == 0 and c == 0)
        ]
        if idx:
            out.append(
                (round(hi, 6), round(sum(correct[i] for i in idx) / len(idx), 6))
            )
    return out


def evaluate_predictions(
    manifest: Mapping[str, Any],
    predictions: Mapping[str, Mapping[str, Any]],
    *,
    genus_of: Mapping[str, str],
    split: str = "test",
) -> dict[str, Any]:
    """Score predictions against one manifest split at genus and species level.

    ``predictions[image_id]`` holds ``ranked_taxon_ids`` (best first),
    optional ``confidence`` (0-1) and ``abstained`` (bool). Open-set images
    are scored on whether the system abstained or flagged an unrepresented
    taxon rather than naming a closed-set species.
    """
    # Re-verify rather than trusting a leakage flag carried in the manifest.
    if not verify_no_leakage(manifest)["passed"]:
        raise ValueError("manifest_failed_leakage_check")
    rows = [e for e in manifest["entries"] if e["split"] == split]
    open_rows = [e for e in manifest["entries"] if e["split"] == "open_set_test"]

    def level_metrics(level: str) -> dict[str, Any]:
        n = answered = top1 = top3 = 0
        confs: list[float] = []
        correct_flags: list[bool] = []
        missing = 0
        for e in rows:
            pred = predictions.get(e["image_id"])
            if pred is None:
                missing += 1
                continue
            n += 1
            truth = (
                e["accepted_taxon_id"]
                if level == "species"
                else genus_of.get(e["accepted_taxon_id"])
            )
            ranked = list(pred.get("ranked_taxon_ids") or [])
            if level == "genus":
                ranked = list(
                    dict.fromkeys(genus_of.get(t) for t in ranked if genus_of.get(t))
                )
            if pred.get("abstained"):
                continue
            answered += 1
            hit1 = bool(ranked) and ranked[0] == truth
            top1 += hit1
            top3 += truth in ranked[:3]
            if pred.get("confidence") is not None and level == "species":
                confs.append(float(pred["confidence"]))
                correct_flags.append(hit1)
        return {
            "evaluated": n,
            "missing_predictions": missing,
            "answered": answered,
            "abstention_rate": round(1 - answered / n, 6) if n else None,
            "top1_accuracy_answered": round(top1 / answered, 6) if answered else None,
            "top3_accuracy_answered": round(top3 / answered, 6) if answered else None,
            "top1_accuracy_overall": round(top1 / n, 6) if n else None,
            "expected_calibration_error": _ece(confs, correct_flags)
            if level == "species"
            else None,
            "reliability_bins": reliability_bins(confs, correct_flags)
            if level == "species"
            else None,
        }

    open_flagged = sum(
        1
        for e in open_rows
        if (p := predictions.get(e["image_id"])) is not None
        and (p.get("abstained") or p.get("unrepresented_taxon"))
    )
    open_scored = sum(1 for e in open_rows if e["image_id"] in predictions)
    return {
        "dataset_version": manifest["dataset_version"],
        "taxonomy_version": manifest["taxonomy_version"],
        "split": split,
        "species": level_metrics("species"),
        "genus": level_metrics("genus"),
        "open_set": {
            "evaluated": open_scored,
            "correctly_flagged_unknown": open_flagged,
            "rate": round(open_flagged / open_scored, 6) if open_scored else None,
        },
        "notes": [
            "metrics evaluate supplied predictions; no model was trained by this function",
            "genus and species metrics are reported separately",
            "accuracy on answered items is reported alongside abstention rate",
        ],
    }
