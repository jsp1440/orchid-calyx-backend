# CALYX-TIG-002 — P1 Hardening

## Purpose

This hardening pass closes the review findings discovered after the initial Trait–Interaction–Genomics (TIG) and Zenodo bridge merge.

## Scientific integrity changes

- TIG hypotheses now require all three evidence domains for each contributing taxon: trait evidence, ecological-interaction evidence, and molecular/genomic evidence.
- Trait-only and two-domain patterns remain admissible evidence but are not promoted to TIG cross-domain hypotheses.
- Archive results are derived server-side from the submitted dataset so client-supplied counts or hypotheses cannot be mixed with a different dataset.
- The archive builder independently verifies dataset identity and evidence count before writing files.

## Archive security changes

- Archive staging root is configuration-controlled; request payloads can no longer override it.
- Dataset identifiers may not be absolute paths or contain path separators.
- Resolved release directories must remain direct children of the configured staging root.

## Publication governance

- Automated Zenodo draft creation remains supported.
- Public Zenodo publication through Calyx is disabled until a durable owner-approved scientific release ledger is implemented.
- The existing publication route is owner-session protected and returns a governance denial rather than invoking Zenodo publication.
- Production Zenodo credentials should remain scoped to `deposit:write` without `deposit:actions` during this phase.

## Runtime/API hardening

- Browser CORS preflight handling now includes `/api/trait-genomics/*`.
- Repeated/upserted hypotheses update their `dataset_id` association as well as payload, confidence, status, and timestamp.

## Validation expectations

Regression coverage verifies:

1. complete three-domain repeated evidence produces a non-causal candidate;
2. trait-only evidence does not produce a TIG candidate;
3. trait + interaction evidence without molecular evidence does not produce a TIG candidate;
4. archive path traversal is rejected;
5. mismatched dataset/result identities are rejected;
6. valid releases remain beneath the configured staging root.

## Governance status

This hardening does not authorize public scientific publication. Zenodo remains a draft-capable, versioned archive target until the reviewed-release ledger and explicit publication approval workflow are implemented.
