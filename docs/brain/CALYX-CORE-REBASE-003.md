# CALYX-CORE-REBASE-003 — Current-main Brain evidence mission lifecycle

## Purpose

Recover the still-missing scientific mission capability from stale PR #391 on current `main` without replacing the current retrieval engine or reviving its ~136-commit-old branch.

## Current-main lifecycle

The bounded mission service connects the existing scientific subsystems in this order:

1. question and bounded deterministic plan;
2. current evidence retrieval;
3. immutable-source reconstruction and Candidate Knowledge extraction;
4. Evidence Aggregation;
5. contradiction and evidence-gap analysis;
6. Scientific Interpretation;
7. Reasoning Ledger creation;
8. structural validation;
9. explicit human-review state;
10. publication-eligibility reporting.

The mission is exposed under the authoritative authenticated Brain router:

- `POST /brain/missions`
- `GET /brain/missions/{mission_id}`

## Provenance boundary

Current evidence retrieval does not provide the stale branch's synthetic `canonical_evidence` payload. The adapter therefore reconstructs an `EvidenceInput` only when the retrieval result can be mapped to exactly one active semantic-index document matching:

- source object type;
- immutable revision ID;
- exact source-anchor sequence;
- a real structured locator.

The matched index record must contain positive `source_object_id`, `revision_id`, and `extraction_run_id` values. Missing or ambiguous identities, unavailable exact anchors, unavailable locators, or unauthorized evidence spans fail closed. No source identity is synthesized.

## Authentication and tenant isolation

Tenant and actor identity are derived exclusively from `verify_owner_or_api_key`. They are not caller-supplied request fields. A cross-tenant mission lookup returns `MISSION_NOT_FOUND` so mission existence is not disclosed to another authenticated subject.

## Governance

- automatic publication is always false;
- optimistic adapter eligibility cannot override `HUMAN_REVIEW_REQUIRED`;
- Reasoning Ledger publication remains governed by the existing version-bound human approval, conflict-resolution, and confidence gate;
- private chain-of-thought is never stored;
- no deployment authority is granted;
- no production Knowledge Graph mutation is granted;
- no taxonomy activation is granted;
- no credentials are exposed.

## Validation contract

Focused validation must prove:

1. a fully successful adapter sequence still stops at `AWAITING_HUMAN_REVIEW` without approval;
2. missing adapters fail closed and cannot become publication eligible;
3. source reconstruction requires one exact active semantic-index identity and rejects ambiguous matches;
4. mission creation derives tenant identity from authentication;
5. cross-tenant status reads are hidden;
6. `/brain/missions` routes are actually mounted on the authoritative Brain router;
7. compile, Ruff, focused pytest, and `git diff --check` pass on the exact head.

## Relationship to stale PR #391

PR #391 is source material only. This recovery adapts its useful mission orchestration to current service contracts and does not merge the old branch directly.
