# AZURE-001 — Governed Evidence Bundle Batch

This batch adds ten controls around the deterministic taxonomy validator. It does not import, publish, deploy, or mutate production data.

1. **Baseline-required mode** — production profiles can reject runs without an approved comparison snapshot.
2. **Input-shape allowlist** — only approved headered or legacy World Plants structures are accepted.
3. **File-suffix allowlist** — unexpected executable or binary extensions fail before parsing.
4. **Candidate-size ceiling** — oversized uploads fail before memory-intensive processing.
5. **Column-count ceiling** — unexpectedly wide or corrupted files fail governance review.
6. **Overall-null-ratio ceiling** — structurally empty datasets fail closed.
7. **Reproducible timestamps** — `SOURCE_DATE_EPOCH` can produce deterministic CI evidence.
8. **Versioned report-contract verification** — missing keys, invalid statuses, or unexpected schema/validator versions are rejected.
9. **Atomic evidence bundles** — report, summary, manifest, and receipt are staged and moved into place only after verification.
10. **Offline integrity verification** — relocation-safe checksums detect modified, missing, or path-escaping artifacts.

## Evidence bundle

A successful governed run creates exactly:

- `report.json`
- `summary.md`
- `manifest.json`
- `receipt.json`

The receipt explicitly records that taxonomy publication and database mutation are not authorized.

## Commands

```bash
python -m runtime.taxonomy_preflight_governance run candidate.csv \
  --baseline approved-baseline.csv \
  --validator-policy config/taxonomy-preflight-policy.json \
  --governance-policy config/taxonomy-preflight-governance.json \
  --output-dir evidence/run-001

python -m runtime.taxonomy_preflight_governance verify evidence/run-001
```

An existing output directory is never replaced. Operators must choose a new run directory, preserving prior evidence.
