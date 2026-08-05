# Calyx Brain Mission Core

This module connects the existing Brain service boundaries into one bounded scientific mission. It coordinates rather than replaces the hybrid evidence retriever, Candidate Knowledge/evidence aggregation, scientific interpretation, Reasoning Ledger, review, and publication-gateway layers.

## Lifecycle and governance

`question -> bounded plan -> evidence retrieval -> evidence aggregation -> contradiction and gap analysis -> scientific interpretation -> Reasoning Ledger creation -> validation -> human review state -> eligible-for-publication state`

Every mission has source, execution-step, and elapsed-time limits. A missing or failing adapter stops the lifecycle with a named blocker while retaining partial evidence. Conclusions are typed separately from source-backed claims. The coordinator accepts and stores no private chain-of-thought. It never invokes publication; eligibility is a status only, always reports `automatic_publication: false`, and requires exact human review plus successful validation.

The production route currently connects the existing deterministic hybrid retrieval engine. Translation from retrieval results into canonical Candidate Knowledge identifiers is intentionally blocked until a safe project-scoped adapter is configured; the route therefore returns partial retrieved evidence plus `AGGREGATE_COMPONENT_UNAVAILABLE` instead of fabricating or bypassing canonical records. All remaining boundaries are exercised deterministically with mocks in `tests/test_brain_mission_core.py`.

## API

Both routes require the existing owner-session or `X-API-Key` authentication.

```http
POST /api/brain/missions
Content-Type: application/json

{
  "question": "Evaluate the accepted taxonomy, geographic distribution, documented pollination biology, conservation concerns, and available mycorrhizal evidence for Laelia anceps.",
  "project_id": "<authorized-research-project-id>",
  "max_sources": 20,
  "max_execution_steps": 10,
  "timeout_seconds": 30
}
```

Retrieve the durable process-local result with `GET /api/brain/missions/{mission_id}`. Production multi-process persistence is an explicit deployment adapter concern; the coordinator repository interface keeps that concern outside scientific orchestration.

## Existing-component audit

| Capability | Existing owner | Mission connection |
|---|---|---|
| bounded planning | no compatible question-level planner | minimal deterministic plan in coordinator |
| semantic retrieval | `app.evidence_retrieval` | connected |
| Candidate Knowledge | `app.candidate_knowledge` | adapter boundary; fail closed |
| aggregation | `app.evidence_aggregation` | adapter boundary; mock-certified |
| contradiction/gaps | aggregation plus orchestration policy | adapter boundary; mock-certified |
| interpretation | `app.scientific_interpretation` | adapter boundary; mock-certified |
| Reasoning Ledger | `app.reasoning_ledger` | adapter boundary; mock-certified |
| human review | Reasoning Ledger/review APIs | mandatory status boundary |
| publication gateway | `app.reasoning_publication` | eligibility read only; publication never called |
