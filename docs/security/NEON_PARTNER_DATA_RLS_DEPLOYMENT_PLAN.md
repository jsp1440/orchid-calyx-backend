# Neon Partner-Data RLS Deployment Plan

Status: implementation plan for the persistent `oc_security` registry.

## Why the registry migration does not grant runtime access

`migrations/111_partner_data_governance_registry.sql` intentionally revokes
PUBLIC privileges and installs no permissive RLS policies on record-policy or
audit surfaces. That is a fail-closed starting point.

A safe RLS policy cannot be bound to guessed database role names. Before a
runtime grant is added, the deployed Neon connection identities used by the
public frontend/API, trusted Calyx backend, workers, migrations, and human
administrators must be identified from the actual environment.

## Required role separation

The target deployment should distinguish at least these responsibilities:

1. **migration owner** — schema evolution only; not used by the public app;
2. **public/read application** — public views only, no protected raw tables;
3. **trusted Calyx evidence service** — policy-mediated protected-data use;
4. **background ingestion worker** — write only to explicitly permitted staging;
5. **security/audit reader** — read audit evidence, no scientific-data mutation;
6. **security/audit writer** — append audit events, no update/delete;
7. **break-glass operator** — exceptional access, separately logged and normally disabled.

A single shared superuser/database-owner credential must not be used for all of
these responsibilities.

## Deployment discovery gate

Before grants or RLS policies are written, record the actual runtime facts:

- `current_user` for each deployed service;
- whether any runtime role has `rolsuper` or `rolbypassrls`;
- schema/table ownership;
- existing grants on scientific and media tables;
- connection pool behavior and whether role/session state can leak between requests;
- whether the public frontend ever connects directly to PostgreSQL;
- migration credential storage and rotation path.

Do not publish credential values in the review artifact.

## RLS enforcement target

For every canonical table that can contain partner-restricted records, the final
state should provide both:

- a record-level link to one or more active `oc_security.dataset_policies`; and
- database enforcement that prevents the public/read role from selecting the raw
  restricted row at all.

Application filtering alone is not sufficient for sensitive locality, restricted
image, unpublished partner, or landowner-controlled evidence.

## Trusted context warning

PostgreSQL custom settings such as `SET oc.principal_id = ...` are not, by
themselves, an authentication boundary because a database role that can issue SQL
can set custom settings. They may be useful as request context only after the
connection role itself has been authenticated and least-privileged.

Do not treat client-supplied session variables as proof of entitlement.

## Policy composition

A record may have multiple active policy bindings. The effective result must be
the intersection / most-restrictive combination:

- any DENY => deny;
- export requires every policy to permit export;
- model processing requires every policy to permit it and the provider to be
  accepted by every provider allowlist that is present;
- locality disclosure uses the most restrictive locality rule;
- image disclosure uses the most restrictive image rule;
- attribution/provenance requirements accumulate rather than disappear.

## Restricted media

Image/file authorization should not rely on an obscured URL. The target is:

- private object storage;
- no permanent public object URL for restricted media;
- short-lived authorized delivery after policy evaluation;
- cache-control appropriate to the restriction;
- no protected media copied into public thumbnails, search caches, exports, or
  AI/provider payloads unless explicitly permitted.

## Audit requirements

Protected-data operations should generate append-only events for at least:

- allowed read;
- denied read;
- export request/result;
- model-processing request/result;
- restricted media access;
- policy/entitlement change;
- break-glass access.

Audit readers must not automatically have permission to inspect the protected
scientific payload itself.

## Validation before accepting partner data

The following tests must pass against a non-production deployment using the
actual role topology:

1. anonymous/public role cannot query raw restricted rows;
2. ordinary authenticated user cannot query raw restricted rows;
3. administrator without dataset entitlement cannot query sealed partner rows;
4. authorized project researcher can perform only the allowed purpose;
5. export is denied when policy prohibits export;
6. an unapproved model provider receives no protected payload;
7. restricted image storage cannot be fetched via a guessed/public URL;
8. direct coordinate disclosure is blocked;
9. derived search/graph results retain policy bindings;
10. connection pooling does not leak one principal's authorization context into
    another request;
11. audit events are written for allow and deny paths;
12. backup/restore retains access-control metadata and does not create an
    unprotected copy.

## Current claim boundary

The existence of `oc_security`, policy code, or RLS-enabled registry surfaces is
not evidence that all scientific domain tables are protected by RLS. The final
Julius/independent review must report separately:

- policy architecture implemented;
- registry persisted;
- RLS scaffolding present;
- specific domain tables protected;
- deployed runtime roles validated;
- end-to-end restricted-data path validated.
