# AZURE-001 — Priority Batch 4

Status: implemented on draft branch; no Azure provisioning or production activation authorized.

## Implemented priorities

1. Required operator review reference for governed runs.
2. Symbolic-link rejection for candidate, baseline, and output targets.
3. Exclusive output lock preventing concurrent writers to one bundle.
4. Deterministic plan-only command that creates no output bundle.
5. Validator, governance, and release-policy SHA-256 provenance.
6. Maximum completed-bundle byte ceiling.
7. Cross-artifact run ID and status consistency verification.
8. Mandatory false safety flags for publication, database mutation, and Azure creation.
9. Checksummed `COMPLETE.json` marker for completed bundles.
10. Pinned-image Azure Container Apps Job specification generator with `provision=false`.

## Safety boundary

The release gate does not create Azure resources, upload files, execute a container, mutate a database, replace the approved taxonomy, or authorize publication. The Azure specification is review evidence only and requires a digest-pinned image.

## Commands

```bash
python -m runtime.taxonomy_preflight_release_gate plan candidate.csv \
  --baseline approved.csv \
  --validator-policy config/taxonomy-preflight-policy.json \
  --governance-policy config/taxonomy-preflight-governance.json \
  --release-policy config/taxonomy-release-gate-policy.json \
  --review-reference OC-REVIEW-YYYY-NNN \
  --output-dir evidence/run-id
```

Change `plan` to `run` only after review. Verify a completed bundle with:

```bash
python -m runtime.taxonomy_preflight_release_gate verify evidence/run-id \
  --release-policy config/taxonomy-release-gate-policy.json
```

Generate a non-provisioning Azure review specification with:

```bash
python -m runtime.taxonomy_preflight_release_gate azure-spec \
  --image ghcr.io/fcos/taxonomy@sha256:<64-hex-digest>
```

## Remaining gates

- GitHub Actions must register and pass.
- The exact August 2026 Hassler file must be validated against the approved prior snapshot.
- Billing alerts and nonprofit-credit linkage must be confirmed before an Azure pilot.
- Container image build, scanning, registry selection, and Azure deployment require separate approval.
