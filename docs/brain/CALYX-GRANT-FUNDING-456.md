# CALYX-456 — Grant and funding opportunity intelligence workspace

Status: IMPLEMENTED / GOVERNED REVIEW-ONLY

## Delivered

- Owner-scoped reusable organization/project profiles with explicit sensitive-field rejection.
- Source-grounded opportunity contracts preserving funder, title, source URL, retrieval time, jurisdiction, currency, amount range, deadline, deadline confidence, eligibility, requirements, contact, and provenance.
- Deterministic 100-point fit scoring across stated entity eligibility, focus-area overlap, geography, requested amount, and deadline confidence.
- Explicit explanations for every score component plus missing-information flags.
- Eligibility is never inferred when the source record is incomplete; missing eligibility is recorded as `unknown` and blocks review readiness.
- Review-only narrative and budget-outline drafts registered as immutable artifacts linked to the official opportunity source.
- Protected Mission Control APIs for profiles, opportunities, assessment, drafts, and readiness.
- Dedicated fixture tests and CI covering provenance preservation, deterministic scoring, missing eligibility, sensitive-data rejection, review-only drafts, governance boundaries, and protected API round trips.

## Governance boundaries

This slice does not submit grants, make binding commitments, contact funders, fabricate eligibility, store credentials/secrets, deploy production changes, mutate the production Knowledge Graph, or authorize merge. Drafts are explicitly marked for human review and preserve the source URL used as evidence.

## Readiness semantics

`REVIEW_READY` means only that the supplied opportunity record contains stated eligibility, the profile matches that stated eligibility, and the deterministic assessment has no missing-information flags. It is not a legal or funder eligibility determination and it is not submission authorization.

## Validation

Dedicated CI compiles the funding runtime/router/Mission Control surface, runs deterministic tests, asserts permanent no-submission/no-outreach/no-secret/no-deployment boundaries, runs Ruff, and checks diff hygiene. The branch remains review-only until exact-head validation completes.
