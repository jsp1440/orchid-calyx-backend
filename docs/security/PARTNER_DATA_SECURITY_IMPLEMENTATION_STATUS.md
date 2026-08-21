# Partner Data Security — Implementation Status

Date: 2026-08-21
Branch: `security/partner-data-foundation`
PR: #1106

## Security objective

Before Orchid Continuum accepts unpublished, landowner-restricted, sensitive-locality, restricted-image, or otherwise partner-controlled scientific data, access and disclosure must be enforced as code rather than as documentation or operator convention.

## Implemented on this branch

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

### Exact occurrence endpoint hardening

A security review found the legacy standalone `api_occurrence_points.py` endpoint returning up to 20,000 exact occurrence coordinate pairs without authentication.

The branch now changes that endpoint to fail closed by default. Exact-coordinate access requires BOTH:

1. an explicit high-friction server-side enable value; and
2. the configured Calyx API key.

This is an emergency compatibility guard only. The legacy exact-coordinate endpoint should not become the delivery mechanism for future partner-restricted data.

### Validation gate

A focused GitHub Actions workflow, `.github/workflows/partner-data-security.yml`, compiles/lints the changed security surface and runs the partner-governance, disclosure, model/output-guard, exact-location, legacy-admin, and Mission Control capability regression tests.

## Existing controls confirmed on current main

- Signed, expiring owner sessions.
- API-key authentication helpers.
- Server-side Mission Control role/capability resolution.
- A distinct restricted-evidence capability.
- Scientific approval authority separated from ordinary administrator status.
- Calyx provider synthesis is optional; deterministic planning remains available without an external language model.

## Not yet complete

This branch is NOT sufficient to accept NAOCC/Smithsonian or other high-sensitivity partner data.

The following remain required:

1. Persistent partner, agreement, dataset-policy, project-authorization, and policy-audit records.
2. PostgreSQL role/RLS implementation on canonical restricted-data storage.
3. Public database roles proven unable to bypass RLS.
4. Policy-aware graph traversal and derived-edge propagation.
5. Policy-aware search and vector/embedding indexing.
6. Integration of the model-processing gate into every Calyx path that can receive governed evidence.
7. Integration of output guarding into every governed synthesis response.
8. Semantic/inference tests for locality reconstruction, not only direct-value leakage.
9. Private storage and short-lived authorized delivery for restricted images/files.
10. Security event logging for restricted reads, denials, exports, model processing, and policy changes.
11. Backup/restore isolation and access-control verification.
12. Route-by-route review of public and administrative application surfaces.
13. Rate limiting/abuse controls and deployment/network review.
14. Independent security review / penetration testing before accepting high-sensitivity partner datasets.

## Acceptance rule

Until these gates are implemented and independently validated, Orchid Continuum should use only public or otherwise explicitly permitted evidence for external demonstrations and should not ingest unpublished/restricted NAOCC partner data.
