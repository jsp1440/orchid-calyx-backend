# OCU-SCI-009H — University durable activation preflight

## Purpose

Provide one read-only command that determines whether the deployed Orchid Continuum University is ready to cross from verified read-only operation into durable learner-session activation.

The preflight never applies migrations, changes environment variables, creates learner records, grants reviewer authority, publishes content, promotes Candidate Knowledge, or enables Calyx model calls.

## Command

```bash
python scripts/preflight_university_activation.py \
  --release-evidence university-production-evidence.json
```

Use `--json` for a machine-readable result.

## Preconditions checked

The preflight requires all of the following while mutating flags remain OFF:

- `OCU_UNIVERSITY_ENABLED=true`
- `OCU_UNIVERSITY_LEARNER_AUTH_ENABLED=true`
- learner Supabase verification settings are present
- `OCU_UNIVERSITY_READ_ONLY_RELEASE_VERIFIED=true`
- `OCU_UNIVERSITY_SESSION_WRITES_ENABLED=false`
- `OCU_UNIVERSITY_DURABLE_SESSIONS_ENABLED=false`
- configured release evidence ID is a valid SHA-256 identifier
- supplied OCU-SCI-007 evidence artifact is itself valid
- artifact SHA-256 exactly matches the configured evidence ID
- target `DATABASE_URL` is reachable
- actual `oc_university` tables contain the required durable columns
- actual database constraints preserve publication/Candidate Knowledge safety invariants
- reviewer qualification registry is structurally valid
- at least one `qualified.science-reviewer` assignment exists for learner submissions

The reviewer check intentionally reports counts only; the preflight artifact does not expose reviewer subject identifiers.

## Governance hinge

The codebase grants no reviewer qualification by default. Therefore the preflight remains blocked until an operator/governance decision assigns at least one actual scientific reviewer.

Expert or publication reviewer grants are not required merely to enable durable learner storage. Candidate Knowledge consideration still requires `review.expert`, and publication authority remains separate.

## Result contract

`OCU-SCI-009H-PREFLIGHT-001`

Key fields:

- `ready_to_enable_durable`
- `blockers[]`
- `environment`
- `release_evidence`
- `database`
- `reviewer_registry`
- `mutations_performed=false`

The command exits zero only when all activation prerequisites are satisfied while writes and durable mode are still disabled.
