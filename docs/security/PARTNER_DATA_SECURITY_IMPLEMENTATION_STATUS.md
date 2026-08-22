# Partner Data Security — Implementation Status

Date: 2026-08-21
Canonical repository: `jsp1440/orchid-calyx-backend`

## Current integration state

- PR #1106, **Security foundation for partner-restricted scientific data**, is merged to `main`.
- PR #1107, **Persist partner governance registry and default-deny RLS scaffolding**, is merged to `main`.
- PR #1108, **Fail closed before generating exact orchid locality maps**, is the current exact-locality hardening candidate.

The repository now contains an application policy layer and a persistent database-governance design. This does **not** mean that live Neon domain tables have been proven partner-data-ready. Repository implementation, migration availability, live migration application, runtime role separation, and end-to-end enforcement are separate verification claims.

## Security objective

Before Orchid Continuum accepts unpublished, landowner-restricted, sensitive-locality, restricted-image, or otherwise partner-controlled scientific data, access and disclosure must be enforced as code rather than as documentation or operator convention.

## Implemented and merged

### Record policy foundation

- Canonical sensitivity classes: `PUBLIC`, `ATTRIBUTED`, `RESEARCH_RESTRICTED`, `SENSITIVE_CONSERVATION`, `SEALED_PARTNER`.
- Source authority retained separately from access rights.
- Purpose restrictions.
- Dataset/partner capability restrictions.
- Independent record, locality, and image disclosure modes.
- Export permission separated from ordinary viewing.
- Model-processing permission separated from ordinary viewing.
- Model-provider allowlist support.
- Fail-closed policy decisions.
- Administrator role does not imply sealed partner-dataset entitlement.

### Disclosure enforcement primitives

- `apply_disclosure()` removes exact location/site/landowner fields when only generalized location disclosure is authorized.
- Image URLs/storage references can be denied independently from scientific record access.
- `EXISTENCE_ONLY` and `AGGREGATE_ONLY` never emit a raw protected record.
- Allowed outputs retain policy/authority metadata so aggregation does not erase provenance or governance.

### External model gate

- `authorize_model_processing()` requires every contributing policy to permit model processing.
- A permissive dataset cannot widen a more restrictive dataset's rule in a multi-source synthesis.
- The requested provider must be declared and, when a policy provides an allowlist, explicitly approved.
- Public viewability does not imply permission for external-model processing.

### Generated-output direct leak guard

- `guard_generated_text()` deterministically redacts exact protected values such as site names, coordinates represented as protected strings, or restricted image URLs when the policy does not authorize their disclosure.
- This is intentionally described as a last-mile direct-leak control, not a complete semantic inference defense.

### Authentication hardening

- Legacy `require_admin()` now fails closed when its server-side key is not configured instead of treating absent configuration as authorization.
- Key comparison uses constant-time `hmac.compare_digest`.

### Exact occurrence API hardening

A security review found the legacy standalone `api_occurrence_points.py` endpoint returning up to 20,000 exact occurrence coordinate pairs without authentication.

It now fails closed by default. Exact-coordinate access requires BOTH:

1. an explicit high-friction server-side enable value; and
2. the configured Calyx API key.

This is an emergency compatibility guard only. The legacy exact-coordinate endpoint should not become the delivery mechanism for future partner-restricted data.

### Persistent partner-governance registry — merged repository implementation

`migrations/111_partner_data_governance_registry.sql` defines a dedicated `oc_security` schema with PUBLIC privileges revoked and persistent records for:

- partner organizations;
- partner agreements;
- versioned dataset policies;
- research projects;
- project memberships;
- dataset/partner-scoped principal entitlements;
- record-to-policy bindings;
- access audit events;
- policy-change events.

The migration enables and forces RLS on the record-policy binding and access-audit surfaces while intentionally installing no permissive policy, creating a default-deny scaffold.

**Claim boundary:** the migration is merged into the repository. This document does not claim it has been applied to the live Neon database or that canonical scientific-domain tables are already protected by live RLS. That requires deployment evidence.

### Validation gates

The focused Partner Data Security workflow and the broader baseline/governance workflows validate the merged security foundation. PR #1106 was merged only after exact-head security, baseline, governance, build, and continuous-completion workflows succeeded. PR #1107 was also merged after its exact-head security and integration gates succeeded.

## Current exact-locality hardening candidate

PR #1108 additionally prevents the legacy `oc_orchid_atlas.py` utility from generating an exact-coordinate browser map merely by importing/running the old script. Exact map generation is disabled by default and requires explicit operator acknowledgement. Public Atlas products should use policy-approved generalized or aggregated locality instead.

## Existing controls confirmed in canonical backend code

- Signed, expiring owner sessions.
- API-key authentication helpers.
- Server-side Mission Control role/capability resolution.
- A distinct restricted-evidence capability.
- Scientific approval authority separated from ordinary administrator status.
- Calyx provider synthesis is optional; deterministic planning remains available without an external language model.

## Not yet complete

Orchid Continuum is **not yet approved to accept NAOCC/Smithsonian or comparable high-sensitivity partner data**.

The following remain required or require live verification:

1. Apply/verify the persistent governance registry in the intended live/non-production Neon environment through the governed migration process.
2. Identify actual Neon runtime roles, ownership, grants, `rolsuper`/`rolbypassrls` state, and connection-pool behavior.
3. Implement and validate RLS on canonical scientific tables that can contain restricted partner records; prove public roles cannot bypass it.
4. Policy-aware Knowledge Graph traversal and derived-edge propagation.
5. Policy-aware search, semantic index, vector/embedding, cache, and export propagation.
6. Integration of the model-processing gate into every Calyx path that can receive governed evidence.
7. Integration of output guarding into every governed synthesis response.
8. Semantic/inference tests for locality reconstruction, not only direct-value leakage.
9. Private storage and short-lived authorized delivery for restricted images/files.
10. Security event logging for restricted reads, denials, exports, model processing, restricted-media access, and policy changes.
11. Backup/restore isolation and access-control verification.
12. Continue route/script/export audit for exact coordinates, restricted media, and bulk-extraction paths.
13. Rate limiting/abuse controls and deployment/network review.
14. Independent security review / penetration testing before accepting high-sensitivity partner datasets.

## Acceptance rule

Until these gates are implemented and independently validated, Orchid Continuum should use only public or otherwise explicitly permitted evidence for external demonstrations and should not ingest unpublished/restricted NAOCC partner data.
