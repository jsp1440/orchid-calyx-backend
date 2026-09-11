# Orchid Continuum Partner Data Security Foundation

Status: **FOUNDATION / NOT YET SUFFICIENT FOR RESTRICTED PARTNER DATA**

This document defines the security architecture required before Orchid Continuum accepts unpublished, contract-restricted, sensitive-locality, partner-controlled, or otherwise non-public scientific data.

## Core principle

Restricted data must remain scientifically useful **without becoming broadly disclosed**.

The architecture therefore separates:

1. **storage permission** — may Orchid Continuum hold the record?
2. **use permission** — may this principal/project analyze it?
3. **model-processing permission** — may an AI/model receive any form of it?
4. **output permission** — what may leave the protected boundary?
5. **export permission** — may the underlying record be copied elsewhere?
6. **provenance/authority** — who owns or remains authoritative for the record?

No layer may silently widen a permission granted by an upstream source agreement.

## Canonical sensitivity classes

- `PUBLIC` — safe for public disclosure.
- `ATTRIBUTED` — public use permitted only with retained source/credit/license conditions.
- `RESEARCH_RESTRICTED` — available only to authenticated, authorized research contexts.
- `SENSITIVE_CONSERVATION` — may include exact localities, vulnerable taxa, landowner-derived information, restricted media, or other conservation-sensitive evidence. Analysis may be allowed while disclosure remains generalized or aggregate-only.
- `SEALED_PARTNER` — partner-controlled information requiring explicit dataset/project capability. No role, including administrator, receives access merely by role inheritance.

The initial policy contract is implemented in `app/data_governance/` and is fail-closed.

## Required enforcement path

```text
User / service / model request
        |
        v
Identity + authenticated principal
        |
        v
Project + declared scientific purpose
        |
        v
Capability / partner entitlement resolution
        |
        v
Record-attached DataPolicy
        |
        v
Policy decision: use + disclosure + locality + image + export + model processing
        |
        +--> DENY
        |
        v
Governed evidence broker / query layer
        |
        v
Calyx deterministic reasoning / approved tools
        |
        v
Optional approved model provider (only when policy permits)
        |
        v
Output disclosure filter + provenance retention
        |
        v
Audited response
```

## Non-negotiable design requirements

### 1. Fail closed

Unknown sensitivity, missing policy, missing identity, missing purpose, missing capability, or unapproved model provider must not default to public access.

### 2. Least privilege

Administrative operation of Orchid Continuum must not automatically grant access to partner-sealed or conservation-sensitive scientific data.

### 3. Provenance and restrictions survive aggregation

An aggregate claim must retain enough lineage to identify its contributing source records, source organizations, licenses/agreements, and disclosure restrictions.

**Aggregation must never destroy the evidence trail or widen access.**

### 4. Bring computation to protected data

For sensitive projects, analysis should occur inside the governed service boundary. Researchers may receive aggregate/generalized outputs without receiving the underlying exact records.

### 5. Model independence and explicit model permission

The scientific database and deterministic Calyx services must remain usable without a generative model. Restricted records may be sent to a model only when the record policy and project agreement explicitly allow model processing, and only to an approved provider/environment.

### 6. Locality inference protection

Hiding latitude/longitude is insufficient. Output filtering must consider whether combinations of county, elevation, dates, landowner, habitat, imagery, specimen metadata, or other features could reconstruct a protected location.

### 7. Restricted images are data

Image authorization must be independent from textual/occurrence authorization. A record can be scientifically usable while its image remains non-displayable and non-exportable.

### 8. Audit every restricted decision

Access attempts, policy decisions, approved uses, denied uses, exports, model-processing events, and disclosure transformations must be auditable without logging protected raw values unnecessarily.

## Defense-in-depth implementation tracks

### Track A — Application policy foundation — STARTED

- [x] sensitivity classes
- [x] source-attached policy contract
- [x] purpose limitation
- [x] capability requirement
- [x] model-processing allow/deny
- [x] model-provider allowlist
- [x] independent locality/image disclosure modes
- [x] export restriction
- [x] fail-closed evaluator
- [x] tests proving administrator status alone does not grant sealed-data access
- [ ] integrate policy decisions into evidence retrieval
- [ ] integrate policy decisions into graph traversal
- [ ] integrate policy decisions into semantic/vector indexing
- [ ] integrate policy decisions into Calyx provider payload construction
- [ ] add output disclosure guard

### Track B — Database isolation / PostgreSQL

Before partner data is accepted:

- [ ] identify canonical restricted-data schemas/tables
- [ ] separate public projections from protected source tables
- [ ] enable and test PostgreSQL Row Level Security where appropriate
- [ ] use distinct least-privilege application roles for public, research, worker, and administrative workloads
- [ ] ensure public/API roles cannot bypass RLS
- [ ] restrict direct database credentials to service identities
- [ ] ensure backups preserve encryption and access controls
- [ ] verify restore procedure into an isolated environment

### Track C — Secrets, network, and service boundary

- [ ] rotate and inventory privileged secrets
- [ ] prohibit database credentials and API secrets in frontend/browser configuration
- [ ] narrow CORS and trusted origins
- [ ] use managed secret storage in the target hosting environment
- [ ] separate public web/API ingress from protected administrative/research operations
- [ ] add rate limiting and abuse controls to public endpoints
- [ ] define network restrictions/private connectivity where supported

### Track D — Restricted media

- [ ] private object storage for non-public images/files
- [ ] short-lived signed retrieval, never permanent public URLs
- [ ] policy check before signed URL generation
- [ ] no restricted media in public CDN/cache
- [ ] watermarking or derivative-only access where partner agreements require it

### Track E — Search, graph, embeddings, and AI

- [ ] prevent restricted evidence from entering public search indexes
- [ ] prevent restricted evidence from entering shared/public vector indexes
- [ ] attach policy identifiers to graph nodes/edges and derived claims
- [ ] policy-aware multi-hop traversal
- [ ] prevent Calyx from retrieving evidence outside the caller's entitlements
- [ ] allow model processing only when explicitly permitted
- [ ] re-check disclosure policy on generated output
- [ ] add tests for inference attacks and indirect locality disclosure

### Track F — Partner/project governance

- [ ] partner registry
- [ ] dataset agreements and agreement references
- [ ] project-scoped authorization
- [ ] embargo/review dates
- [ ] approved purposes
- [ ] approved model environments
- [ ] retention/deletion obligations
- [ ] revocation process
- [ ] attribution format required by partner

### Track G — Security operations

- [ ] security event/audit log
- [ ] anomaly/rate monitoring
- [ ] incident response procedure
- [ ] credential-compromise procedure
- [ ] breach notification decision tree
- [ ] dependency/security scanning in CI
- [ ] secret scanning
- [ ] external penetration test before accepting high-sensitivity partner data

## Existing relevant controls discovered on current main

The current backend already contains useful foundations, including:

- API-key and signed owner-session authentication in `app/security.py`;
- server-side role/capability resolution in `app/mission_control_access/`;
- a distinct `review.evidence.restricted` capability for expert review;
- administrative status intentionally separated from scientific-review authority;
- Calyx's external provider used as optional governed synthesis rather than as the authority for server-side intent/actions;
- Research Station frontend guidance that production credentials must never be stored in browser variables.

These are useful building blocks, but they are **not sufficient by themselves** for partner-restricted data.

## Current security findings requiring follow-up

1. The present authorization model is principally application capability/authentication oriented; record-attached partner restrictions are not yet consistently enforced across database, graph, search, media, and Calyx output surfaces.
2. Restricted scientific evidence has a role capability, but sensitive locality, partner-sealed data, model-processing permission, image rights, purpose limitation, and export rights require finer-grained policy.
3. A complete PostgreSQL/RLS and service-role audit is still required.
4. A route-by-route authorization audit is required, including confirmation that no administrative helper can fail open when a secret/configuration is absent.
5. Existing public/prototype surfaces must be checked for scientific assertions that lack inspectable provenance or expose more locality/media information than intended.

## Acceptance gate before accepting NAOCC/Smithsonian restricted data

Orchid Continuum must not claim to be ready for restricted partner data until all of the following have independent evidence:

- authenticated least-privilege access;
- project/dataset-scoped authorization;
- fail-closed record policies;
- database-level protection for protected records;
- restricted media controls;
- provenance preservation;
- policy-aware graph/search/retrieval;
- model-processing allowlists;
- output/inference protection;
- complete auditability;
- tested backup/restore;
- incident response;
- external security review or penetration testing appropriate to the sensitivity class.

Until that gate is met, use public data only for demonstrations and scientific validation.
