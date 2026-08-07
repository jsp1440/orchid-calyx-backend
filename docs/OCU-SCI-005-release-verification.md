# OCU-SCI-005 — Read-Only University Release Verification

## Purpose

Provide a deterministic, non-sensitive release contract for the first deployed Orchid Continuum University experience.

## Endpoint

`GET /api/learning/release-readiness`

The endpoint reports configuration and governance state only. It does not expose credentials, raw environment values, learner records, or unpublished scientific data.

A safe first release must report:

```json
{
  "release_contract": "OCU-RELEASE-001",
  "university_enabled": true,
  "read_only_ready": true,
  "session_writes_enabled": false,
  "publication_enabled": false,
  "candidate_knowledge_writes_enabled": false,
  "calyx_model_calls_enabled": false,
  "human_review_required": true
}
```

## Required configuration

```text
OCU_UNIVERSITY_ENABLED=true
OCU_UNIVERSITY_SESSION_WRITES_ENABLED=false
```

This phase intentionally retains process-local persistence and disables learner writes. Durable learner records are not permitted until the read-only deployment is reachable and verified.

## Automated verification

Repository tests:

```bash
python -m unittest \
  tests/test_university_session_service.py \
  tests/test_university_release_readiness.py
```

Deployed smoke test:

```bash
python scripts/smoke_university_release.py https://<calyx-host>/api
```

The smoke test verifies:

1. release-readiness governance state;
2. capability response;
3. chapter and laboratory identifiers in the catalog;
4. retrieval of the flowering chapter;
5. retrieval of the Failure-to-Bloom laboratory.

It fails when session writes, publication, Candidate Knowledge writes, or model calls are enabled.

## Governance boundary

The contract can prove that a deployed backend is configured safely. It cannot assign DNS, replace the Famous.ai deployment, configure Render or another host, or select the production domain. Those actions remain tracked in frontend issue #95.
