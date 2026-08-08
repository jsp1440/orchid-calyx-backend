# CALYX-456 — Grant and funding opportunity intelligence workspace

Status: IMPLEMENTED / EXACT-HEAD VALIDATED / GOVERNED REVIEW-ONLY

## Delivered

- Owner-scoped reusable organization/project profiles with explicit sensitive-field rejection.
- Source-grounded opportunity contracts preserving funder, title, source URL, retrieval time, jurisdiction, currency, amount range, deadline, deadline confidence, eligibility, requirements, contact, and provenance.
- Deterministic 100-point fit scoring across stated entity eligibility, focus-area overlap, geography, requested amount, and deadline confidence.
- Explicit explanations for every score component plus missing-information flags.
- Eligibility is never inferred when the source record is incomplete; missing eligibility is recorded as `unknown` and blocks review readiness.
- Review-only narrative and budget-outline drafts registered as immutable artifacts linked to the official opportunity source.
- Repeated draft generation is content-stable and safe against immutable-registry conflicts.
- Protected Mission Control APIs for profiles, opportunities, assessment, drafts, and readiness.
- Dedicated fixture tests and CI covering provenance preservation, deterministic scoring, missing eligibility, sensitive-data rejection, review-only drafts, immutable artifact stability, governance boundaries, and protected API round trips.

## Governance boundaries

This slice does not submit grants, make binding commitments, contact funders, fabricate eligibility, store credentials/secrets, deploy production changes, mutate the production Knowledge Graph, or authorize merge. Drafts are explicitly marked for human review and preserve the source URL used as evidence.

## Readiness semantics

`REVIEW_READY` means only that the supplied opportunity record contains stated eligibility, the profile matches that stated eligibility, and the deterministic assessment has no missing-information flags. It is not a legal or funder eligibility determination and it is not submission authorization.

## Validation

Exact-head validation completed on commit `d44193f40ae155d335bcc92905e735c4a95476bc`.

- CALYX Grant Funding 456: success; compile, 8 deterministic tests, permanent governance assertions, Ruff, and diff hygiene all passed.
- CALYX Workflow Governance Audit: success.
- CALYX-AUTONOMY-DEPLOYMENT-001: success.
- CALYX-SUPERVISED-PILOT-001: success.
- CALYX Literature Acquisition 448 dependency regression: success.
- CALYX Research Station 453 dependency regression: success.

PR #613 remains draft/unmerged and targets `feature/calyx-research-station-453` because the funding workspace depends on Research Station and its artifact/review foundations.
