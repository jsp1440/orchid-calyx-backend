# OCU-SCI-009G — Governed University reviewer workspace

## Purpose

Prepare the instructor/scientific-review frontend contract without weakening the existing Mission Control reviewer authority model.

## Reviewer identity

University learner identity and reviewer identity remain separate.

Learners use verified Supabase identity. Reviewers use the existing Mission Control owner-session principal path, followed by capability and scientific-qualification resolution.

Administrator status does not imply scientific authority.

## Server-controlled qualification registry

`MISSION_CONTROL_REVIEWER_QUALIFICATIONS_JSON` may provide scientific qualifications for a named owner-session subject. Missing configuration grants no scientific qualification.

Example schema (illustrative only; this repository change does not assign it):

```json
{
  "owner": {
    "qualifications": ["qualified.science-reviewer"],
    "qualification_expires_at": {
      "qualified.science-reviewer": "2027-01-01T00:00:00Z"
    },
    "specialties": ["orchid taxonomy"]
  }
}
```

Allowed qualification names are deliberately restricted to:

- `qualified.science-reviewer`
- `qualified.expert-reviewer`
- `qualified.publication-reviewer`

Unknown or malformed entries fail closed. Expired qualifications are removed by the existing `PrincipalResolver`. API-key identities cannot obtain scientific qualifications from this registry.

**Assigning an actual reviewer qualification is a governance/operator decision and is not performed by OCU-SCI-009G.**

## University reviewer endpoints

- `GET /api/learning/reviewer/context`
  - reports resolved roles, active scientific qualifications, effective capabilities, and whether science/expert review is permitted
  - does not require durable mode to be active, allowing the frontend to represent a locked reviewer state truthfully

- `GET /api/learning/reviewer/sessions`
  - requires a qualified `review.science` principal and verified durable University activation
  - returns only submitted/under-review session summaries
  - keyset paginated, maximum 50

- `GET /api/learning/reviewer/sessions/{session_id}`
  - requires the same qualified reviewer authority and durable activation
  - returns the scientific event payloads and prior review history needed for review
  - deliberately strips learner actor IDs, event actor IDs, and reviewer actor IDs

The existing decision endpoint remains authoritative:

`POST /api/learning/sessions/{session_id}/reviews`

Learning/changes-requested decisions require `review.science` plus a scientific qualification. Candidate Knowledge consideration requires `review.expert` plus a scientific qualification. Candidate Knowledge is not automatically promoted and publication remains outside the University review transaction.

## Runtime boundary

This build does not:

- configure a real reviewer qualification
- enable University durable flags
- execute the University migration
- publish learner work
- promote Candidate Knowledge
- enable Calyx model calls
- grant scientific authority to learner or API-key identity
