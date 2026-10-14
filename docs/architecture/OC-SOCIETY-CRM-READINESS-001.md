# OC-SOCIETY-CRM-READINESS-001 — Multi-Society CRM Readiness Audit

Date: 2026-09-26
Status: audit complete; implementation required before production society use
Target: FCOS shadow pilot first, then one outside plant society, then broader multi-tenant rollout

## Executive conclusion

Orchid Continuum contains a real constituent/communications foundation, but it is **not yet a production CRM and is not ready to replace Neon One**.

The repository already has:
- an `oc_constituent` PostgreSQL schema with organizations, constituents, identity links, email, phone, postal address, memberships, entitlements, preferences, suppressions;
- an `oc_communications` schema with communication intents, immutable audience snapshots, audience members, and approval events;
- domain policy code and CI validation for normalization, consent/suppression decisions, audience hashing, approval boundaries, and frozen-audience immutability;
- public newsletter/contact APIs and tests;
- member authentication infrastructure for read-only product access;
- frontend society and organization-profile entry points.

However, the current newsletter/contact service writes to the generic Research Station record store rather than the canonical `oc_constituent` / `oc_communications` tables, while the membership tables are not consumed by application services. The society frontend explicitly remains a placeholder waiting for governed society APIs. Payment processing, donations, renewals, event registration, member portal, tenant administration, roster export, support diagnostics, and production tenant isolation are not yet implemented end-to-end.

Therefore the correct readiness state is:

**Foundation built; Neon replacement not ready; controlled shadow pilot only after the blockers below pass.**

## Evidence observed in repository

### Implemented foundation
- `migrations/20260823_oc_constituent_communications_foundation.sql`
  - `oc_constituent.organizations`
  - `oc_constituent.constituents`
  - `oc_constituent.identity_links`
  - `oc_constituent.email_addresses`
  - `oc_constituent.phone_numbers`
  - `oc_constituent.postal_addresses`
  - `oc_constituent.memberships`
  - `oc_constituent.entitlements`
  - `oc_constituent.communication_preferences`
  - `oc_constituent.suppressions`
  - `oc_communications.intents`
  - `oc_communications.audience_snapshots`
  - `oc_communications.audience_members`
  - `oc_communications.approval_events`
- `app/constituent_platform/domain.py`
  - membership states
  - communication purposes
  - preference/suppression policy
  - approval requirements
  - audience hashing and state-transition checks
- `.github/workflows/oc-constituent-platform-validation.yml`
  - applies schema in PostgreSQL 16
  - verifies idempotency
  - verifies frozen audience immutability
  - runs domain regression tests
- `app/constituent_platform/routes.py` + tests
  - subscribe / unsubscribe
  - preference center
  - newsletter archive
  - public contact intake
  - owner contact inbox and subscription summary
- `app/member_auth.py`
  - verified Supabase member read access
  - default-deny write boundary
  - owner/API-key separation
- frontend:
  - `src/pages/Societies.tsx` describes intended events, rosters, renewals, newsletters, judging, educational tools
  - `src/pages/OrganizationProfile.tsx` is explicitly a placeholder pending governed APIs

## Critical architectural gap

The canonical SQL CRM schema and the currently exposed constituent service are not yet one system.

`app/constituent_platform/service.py` currently stores subscriptions, welcome intents, newsletter issues, and contact messages in `oc_admin.research_station_records` through the Research Station store. Searches of application code show no runtime use of `oc_constituent.memberships`, `oc_constituent.organizations`, or `oc_constituent.entitlements` outside the migration.

Before production society use, application services must converge on the canonical CRM schema or provide a deliberate migration/adapter boundary with a single source of truth.

## Neon-replacement capability matrix

| Capability | State | Production requirement |
|---|---|---|
| Organizations / societies | Foundation only | tenant CRUD + verified org profile + settings |
| Person/member records | Foundation only | CRUD + dedupe + import + audit |
| Email/phone/address | Schema built | tenant-scoped service/UI |
| Membership status | Schema built | service/UI + expiry/grace rules |
| Membership levels | level_code only | configurable level catalog + prices/benefits |
| Renewals | Missing | renewal workflow + ledger + notifications |
| Dues payments | Missing | provider adapter + webhook/idempotency + ledger |
| Donations | Missing | donation records + receipts + designation |
| Offline/check/cash payments | Missing | treasurer recording with audit |
| Member portal | Missing | self-service profile, membership, receipts, preferences |
| Society officers/staff roles | Missing | tenant role assignments + least privilege |
| Member directory | Missing | opt-in directory + privacy controls |
| Newsletter preferences | Partial | migrate to canonical schema + production sender |
| Newsletter sending | Deferred | approved provider adapter + delivery/bounce handling |
| Events | Missing | event CRUD |
| Event registration | Missing | registration + capacity/waitlist/payment linkage |
| Roster export | Missing | CSV export with authorization + audit |
| Neon import | Missing | idempotent import + dry-run + discrepancy report |
| Audit trail | Partial | CRM-specific append-only audit across writes |
| Tenant isolation | Unproven | RLS/service enforcement + cross-tenant negative tests |
| Backup/restore | Unproven | tested restoration of CRM data + policy metadata |
| Support diagnostics | Missing | safe admin health/errors/jobs/webhook status |
| Public society page | Placeholder | governed public endpoint + frontend |
| Join link | Missing | public membership signup |
| Forum/community | Separate work | public/private community module after CRM core |
| Knowledge graph access | Existing OC capability | entitlements can expose member benefits |

## Hard production blockers

P0 blockers before FCOS can be a shadow pilot:
1. one canonical CRM source of truth;
2. organization-scoped authorization model;
3. tenant isolation tests that prove Society A cannot access Society B;
4. membership-level catalog and member CRUD;
5. import/export with reconciliation;
6. audit log for administrative writes;
7. backup/restore proof.

Additional P0 blockers before Neon can be cancelled:
8. renewal workflow;
9. payment ledger plus at least one production payment provider;
10. offline/check payment recording;
11. member self-service portal;
12. event registration if FCOS relies on Neon for it;
13. production communications path for required membership email;
14. documented incident/recovery procedure.

## Pilot model

### Phase A — synthetic tenant validation
Create two synthetic organizations with overlapping names/emails. Run all CRUD, export, membership and permission tests. No real member data.

Exit criteria:
- all cross-tenant negative tests pass;
- backup/restore exercise passes;
- no workflow requires direct database intervention.

### Phase B — FCOS shadow pilot
Neon remains system of record. Import a snapshot into OC and reconcile daily/weekly during the pilot.

Required real workflows:
1. create new member;
2. renew existing member;
3. record check/cash payment;
4. change member address/email;
5. lapse/restore a member;
6. export roster;
7. send or queue membership communication with consent rules;
8. register for an event if in scope;
9. member self-service update;
10. recover from duplicate/import conflict.

Exit criteria:
- zero unexplained discrepancies with Neon for an agreed observation period;
- ordinary FCOS administrator can complete the workflows without developer intervention;
- recovery test completed from backup.

### Phase C — outside-society pilot
Use one friendly non-FCOS plant society to expose FCOS-specific assumptions.

Exit criteria:
- separate tenant data remains isolated;
- configurable membership levels/renewal settings work without custom code;
- support issues are diagnosable through admin tooling rather than repository edits.

### Phase D — limited multi-tenant rollout
Only after Phases A-C pass. Increase tenants gradually. Do not create separate deployments per society.

## Multi-tenant product principle

The product must be:
- one codebase;
- one deployable platform;
- one schema family;
- shared operations and monitoring;
- organization-scoped data and authorization;
- configuration instead of per-society forks.

Do not create one CRM deployment or code fork per society.

## Reliability / support acceptance tests

A production candidate must automatically test:
- duplicate email/person reconciliation;
- membership start/expiry/grace/lapse transitions;
- payment webhook idempotency;
- failed payment and retry;
- offline payment audit;
- donation receipt data;
- unsubscribe/bounce suppression;
- event capacity/waitlist transitions;
- tenant A cannot read/write/export tenant B;
- member cannot elevate to officer/admin;
- deleted/lapsed membership does not retain protected entitlements;
- CSV export authorization and audit;
- backup restore preserves tenant, membership, preference and audit state;
- safe handling of provider outage;
- safe handling of duplicate webhooks;
- safe retry of imports;
- no member PII in logs/telemetry beyond approved fields.

## Pricing decision

Do not set external pricing until FCOS and one outside society have passed pilots. Technical cost and support burden must be measured, not guessed.

## Cancellation gate for Neon

Neon One should not be cancelled until:
- all P0 blockers are closed;
- FCOS completes the shadow pilot;
- payment and renewal reconciliation is proven;
- restore/recovery has been tested;
- at least two administrators other than the developer can operate the system;
- a full export from OC can be produced independently;
- there is a rollback plan back to Neon/exported data.

## Immediate work order

1. Canonical CRM persistence + tenant context.
2. CRM authorization/RLS + cross-tenant tests.
3. Membership levels, members, lifecycle and audit.
4. Import/export and FCOS reconciliation tooling.
5. Payments/donations/renewals.
6. Member portal.
7. Events/registration.
8. Communications provider integration.
9. Support diagnostics + backup/restore drill.
10. FCOS shadow pilot.
11. Outside society pilot.
12. Only then forum/community and broader commercialization.
