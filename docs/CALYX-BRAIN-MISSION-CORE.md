# Calyx Brain Mission Core

This module connects the existing Brain service boundaries into one bounded scientific mission. It coordinates rather than replaces the hybrid evidence retriever, Candidate Knowledge/evidence aggregation, scientific interpretation, Reasoning Ledger, review, and publication-gateway layers.

## Lifecycle and governance

`question -> bounded plan -> evidence retrieval -> evidence aggregation -> contradiction and gap analysis -> scientific interpretation -> Reasoning Ledger creation -> validation -> human review state -> eligible-for-publication state`

Every mission has source, execution-step, and elapsed-time limits. A missing or failing adapter stops the lifecycle with a named blocker while retaining partial evidence. Conclusions are typed separately from source-backed claims. The coordinator accepts and stores no private chain-of-thought. It never invokes publication; eligibility is a status only, always reports `automatic_publication: false`, and requires exact human review plus successful validation.

The production route connects the deterministic hybrid retrieval engine to the existing Candidate Knowledge extractor, evidence aggregation service, scientific interpretation service, and Reasoning Ledger service. Retrieval now projects only canonical identities, anchors, provenance, authorized evidence spans, and structured candidate facts already held by the semantic index. Sources missing any required identity, anchor, locator, or authorized span are reported as translation gaps; none are synthesized. If every result is incomplete, the mission fails explicitly with `NO_CANONICAL_RETRIEVAL_EVIDENCE`.

The route currently uses the existing in-memory repositories used by these service implementations, matching the mission repository's process-local lifetime. Durable multi-process production persistence remains a deployment adapter concern; scientific transformations and governance are no longer mock-only.

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
| Candidate Knowledge | `app.candidate_knowledge` | connected through canonical retrieval translation |
| aggregation | `app.evidence_aggregation` | connected |
| contradiction/gaps | aggregation plus orchestration policy | connected |
| interpretation | `app.scientific_interpretation` | connected |
| Reasoning Ledger | `app.reasoning_ledger` | connected; review pending |
| human review | Reasoning Ledger/review APIs | mandatory status boundary |
| publication gateway | `app.reasoning_publication` | eligibility read only; publication never called |
