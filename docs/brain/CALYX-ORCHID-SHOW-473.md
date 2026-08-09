# CALYX-473 — Orchid show, judging, entries, awards, and event operations

Status: IMPLEMENTED / VALIDATION RETRYING / HUMAN-JUDGED

## Delivered

- Owner-scoped orchid show records with venue, schedule, status, and governance state.
- Private exhibitor records; result exports never include private contact data.
- Entry classes and plant entries preserving the exhibitor-entered label exactly as entered while storing canonical taxon ID and accepted-name display separately.
- Explicit taxonomy review state when canonical identity is incomplete; no autonomous identification is authorized.
- Judging-team records with judge IDs, class assignments, and conflict declarations.
- Human-only ribbon, trophy, special-award, and no-award decisions with deciding judges, rationale, conflict-resolution requirements, immutable decision digest, and audit history.
- Event schedule items, vendor records, and volunteer assignments integrated with the CALYX-472 private volunteer contract.
- Printable entry-label payloads and privacy-safe results exports.
- Append-style event audit history and protected Mission Control APIs.
- Deterministic tests covering label/canonical-name separation, human judging, conflict resolution, privacy, volunteer integration, owner isolation, and permanent authority boundaries.

## Integration model

CALYX-473 is stacked on CALYX-472 because show volunteer assignments reuse the private owner-scoped volunteer profile contract rather than introducing a second volunteer identity store. Entries support canonical taxon identifiers and accepted-name display while preserving the exact entered label text as historical show evidence. Media references are stored only as reviewed artifact identifiers; this build does not invent media eligibility or scientific identification authority.

## Judging and governance boundaries

Awards are never computed or granted autonomously. `record_judging_decision` rejects any decision unless `human_decision=true`, requires named deciding judges from the recorded judging team, requires rationale, and requires explicit conflict resolution whenever conflicts are recorded.

No payment processing is implemented. Vendor records explicitly report payment as unmanaged by Calyx. No public personal-data exposure is authorized. This build does not deploy, merge, publish scientific claims, or mutate the production Knowledge Graph.

## Validation

Dedicated CI compiles the show runtime/router/Mission Control surface, runs CALYX-473 plus CALYX-472 regressions, enforces permanent human-judging/privacy/no-payment boundaries, runs Ruff, and checks diff hygiene.

The first pull-request validation attempt failed before any job step started. CALYX-473, CALYX-472, supervised-pilot, and autonomy workflows all returned failed jobs with no steps, and the job-log blob was unavailable. This is consistent with a hosted-runner provisioning failure rather than a code/test failure. No assertion or validation gate was weakened. This documentation commit intentionally triggers a clean retry; exact-head evidence must be recorded only after a runner executes the workflow steps.
