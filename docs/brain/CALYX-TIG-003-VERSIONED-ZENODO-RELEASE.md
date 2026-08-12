# CALYX-TIG-003 — Versioned Zenodo Scientific Release Workflow

## Purpose

Calyx TIG now has a governed path from operational Trait–Interaction–Genomics evidence to a durable, citable Zenodo draft without allowing automated publication.

The archive layer is designed for scientific snapshots rather than mutable operational state. Neon/Postgres remains authoritative for live evidence, hypotheses, review state, and archive ledger state. Zenodo receives reproducible release packages for long-term scientific preservation and eventual DOI-backed publication after human review.

## Release pipeline

1. Accept a `DiscoveryDataset` containing provenance-bearing trait, ecological-interaction, and molecular/genomic evidence.
2. Recompute TIG hypotheses server-side so archive contents cannot be paired with a caller-supplied result from another dataset.
3. Build a deterministic release package beneath `CALYX_SCIENTIFIC_ARCHIVE_STAGING`.
4. Write:
   - `trait_interaction_genomics_evidence.jsonl`
   - `discovery_hypotheses.jsonl`
   - `README.md`
   - `manifest.json`
5. SHA-256 checksum the scientific content files.
6. Compute a deterministic release fingerprint from dataset identity plus file checksums.
7. Check the Neon archive ledger for an existing Zenodo release with that fingerprint.
8. Reuse the existing record if found, preventing duplicate deposits of identical scientific content.
9. Otherwise create an unpublished Zenodo deposition draft in the configured community.
10. Persist `draft_created` in Neon before file upload.
11. Upload all release files to the Zenodo draft bucket.
12. Persist `draft_uploaded`, or `upload_failed` with bounded error detail if upload fails.
13. Keep public publication disabled in Calyx until a separately governed owner-approved scientific-release workflow exists.

## Durable ledger

`calyx_scientific_archive_releases` records:

- provider and deposition identity
- dataset identity
- deterministic release fingerprint
- current archive state
- Zenodo community
- release manifest
- compact provider metadata
- staging path
- creation/update timestamps

Uniqueness on `(provider, deposition_id)` and `(provider, release_fingerprint)` prevents accidental duplication and supports idempotent retry.

## Scientific integrity

The archive package preserves the distinction between evidence and hypothesis. TIG hypotheses remain non-causal candidate associations until phylogenetic correction, replication, and mechanistic review support stronger interpretation.

The manifest records evidence-domain counts, hypothesis count, provenance snapshot IDs, checksums, fingerprint, archive policy, publication policy, and causal policy.

## Publication boundary

Automated archive creation is draft-only. The Calyx API returns HTTP 403 for its publication route, and the production Zenodo token is intentionally configured without publication authority. A future publication path must require a durable scientific approval record and owner-specific authorization before any automated public action can be considered.

## Live integration evidence — 2026-08-12

The production Render service authenticated successfully to Zenodo and created an unpublished integration-test draft in the `orchid-continuum` community:

- deposition ID: `21909610`
- state: `unsubmitted`
- submitted: `false`
- DOI: none

The test established successful Calyx-to-Zenodo draft creation without public publication. The subsequent publication attempt remained blocked; no DOI was minted and the record remained unpublished.

## Validation contract

The repository includes a focused `CALYX TIG Zenodo Validation` workflow. It executes TIG discovery, scientific hardening, Zenodo packaging, release-service tests, subsystem compilation, and Ruff checks whenever the TIG/archive surface changes. Archive workflow changes are not merge-ready until this focused validation and applicable repository governance checks are green.

## Operational configuration

Required runtime variables:

- `DATABASE_URL`
- `ZENODO_ACCESS_TOKEN`
- `ZENODO_API_BASE=https://zenodo.org/api`
- `ZENODO_COMMUNITY=orchid-continuum`
- `CALYX_SCIENTIFIC_ARCHIVE_STAGING` (defaults to `/var/data/scientific_archive_staging`)

Secrets must never be stored in source control or Brain documentation.
