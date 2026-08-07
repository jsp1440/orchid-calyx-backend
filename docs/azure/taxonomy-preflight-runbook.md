# Taxonomy Preflight Operator Runbook

Status: non-production review workflow. The validator cannot import, publish, replace, or activate taxonomy data.

## Inputs

- candidate World Orchids / World Plants file;
- previously approved snapshot as baseline;
- reviewed policy file at `config/taxonomy-preflight-policy.json`.

Keep the original files unchanged. Record the source email or delivery location outside the validator when required by the evidence system.

## Command

```bash
python -m runtime.taxonomy_preflight \
  "WorldOrchids 26-08 (Aug 2 2026).csv" \
  --baseline "approved-world-orchids.csv" \
  --policy config/taxonomy-preflight-policy.json \
  --json-output artifacts/taxonomy-preflight-report.json \
  --summary-output artifacts/taxonomy-preflight-summary.md \
  --manifest-output artifacts/taxonomy-preflight-manifest.json
```

## Exit codes

- `0`: PASS or WARN; artifacts were produced. WARN still requires review.
- `2`: FAIL; artifacts were produced and promotion is prohibited.
- `3`: execution/configuration error; inputs or policy could not be safely evaluated.

## Ten enforced controls

1. Versioned report schema.
2. Deterministic run identifier from source, baseline, policy, and validator version.
3. Candidate and baseline SHA-256 provenance.
4. Governed, fail-closed threshold policy.
5. Removed-taxon ratio gate.
6. Changed-taxon ratio gate.
7. Minimum row-count gate.
8. Missing-identity and duplicate-key ratio gates.
9. Atomic report/summary/manifest writes.
10. Checksummed artifact manifest for later evidence ingestion.

## Review sequence

1. Confirm source and baseline filenames/checksums.
2. Confirm detected input shape and delimiter.
3. Review row count and record-type distribution.
4. Review FAIL findings first.
5. Review added, removed, and changed samples.
6. Compare aggregate changes with the supplier's release notes, when available.
7. Preserve all three generated artifacts.
8. Require an explicit human approval and a separate import workflow before taxonomy activation.

## Stop conditions

Do not proceed when:

- status is FAIL;
- baseline is absent for a replacement release;
- row count drops unexpectedly;
- removed or changed ratios exceed policy;
- source or baseline checksum is unexplained;
- input shape is unknown;
- the operator cannot identify the authoritative previously approved snapshot.

## Azure pilot mapping

The same command may later run as an on-demand Azure Container Apps Job reading private Blob objects. Azure execution does not change the scientific gate: outputs remain review artifacts only, and there is no database or publication permission.
