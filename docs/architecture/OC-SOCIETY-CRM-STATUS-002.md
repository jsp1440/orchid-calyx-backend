# OC-SOCIETY-CRM-STATUS-002 — Multi-society CRM: what is built, what is proven, what is not

Date: 2026-09-27
Supersedes nothing; extends `OC-SOCIETY-CRM-READINESS-001` (branch `chatgpt/society-crm-readiness-20260926`).
Status: **not production-ready; not a Neon One replacement.** Backend P0 slices exist with automated
PostgreSQL proof; nothing is deployed or enabled in production.

## One platform, many tenants

One codebase, one deployment (Render), one schema family (`oc_constituent`, `oc_communications`),
many organizations. A society is a row in `oc_constituent.organizations`; its configuration
(levels, dues, terms, grace, household size, roles) is data, not code.

## Source-of-truth contract

| Data | Canonical home | Notes |
|---|---|---|
| Society people | `oc_constituent.constituents` with `owner_organization_id` | Tenant-owned. The same human in two societies is two records; editing one never changes the other. |
| Memberships, levels, renewals, household | `oc_constituent.memberships`, `membership_levels`, `membership_renewals`, `membership_household_members` | Composite `(organization_id, …)` FKs make cross-tenant references impossible. |
| Staff authority | `organization_staff_roles` reached **only** through an active `organization_identity_bindings` row in the same organization | Membership never implies a role. |
| Consent | `communication_preferences` (append-only ledger) + `suppressions` | Per organization. |
| Communications | `oc_communications.intents`, frozen `audience_snapshots`/`audience_members`, `approval_events`, `delivery_attempts`, `delivery_events` | |
| Import provenance | `external_record_links` | One link per source record; repeat imports are idempotent. |
| Audit | `crm_audit_events` (append-only, trigger-enforced) | Written in the same transaction as the change. |
| Platform newsletter/contact (Orchid Continuum's own) | **Selectable, exactly one at a time**: `OC_CONSTITUENT_PERSISTENCE=research_station` (default, current production) or `canonical` | Cutover: run `scripts/oc_constituent_migrate_research_station.py` (dry run default), resolve every discrepancy, `--apply`, re-run until `cutover_ready`, then flip the variable. The canonical selection fails closed (503) and never falls back. |

## Isolation model

1. Service layer: `SocietyCRMService` resolves the caller's roles in the target organization on every call (no cache — revocation is immediate), default deny, least-privilege capabilities.
2. Repository: every tenant query filters by `organization_id` **and** runs under `SET LOCAL ROLE oc_crm_runtime` with a transaction-local tenant setting; row-level security hides other tenants even from a query with no `WHERE`.
3. Schema: composite tenant FKs; runtime role has no DELETE, append-only audit/ledger tables, no grants outside the CRM schemas.
4. Pooled connections: role and tenant are transaction-local and vanish at COMMIT/ROLLBACK (tested on one reused connection across tenants and a failed request).

RLS is defence in depth, not an authentication boundary (see `docs/security/NEON_PARTNER_DATA_RLS_DEPLOYMENT_PLAN.md`).

## Household / family membership decision

Implemented: one primary membership carries dues, status and dates; additional people are
`membership_household_members` rows. `membership_levels.household_max_members` counts the primary
member (a Family level of 3 = primary + 2). Household members are tenant-owned people and may
link their own portal login. Downgrading a level below the current household size is refused.

## Proven by automated tests (PostgreSQL 16; CI workflow `oc-society-crm-p0-validation.yml`)

- Two societies with identical names and member emails: no read/search/update/export/audit/role crossover (service, repository, raw SQL, RLS, HTTP).
- Member ≠ admin; self-promotion refused; treasurer/membership-editor/viewer limits; immediate revocation; last admin protected; identity bindings cannot be silently re-pointed; platform operator has no implicit data access.
- Lifecycle: pending→active (renewal), active→grace→lapsed (idempotent job), lapsed→active, early/grace renewal terms, cancellation/reinstatement with reason, level changes audited, society-only entitlements follow status.
- Import: dry run writes nothing; repeat import creates nothing; conflicts reported, never overwritten; invalid rows reported with counts that add up; reconciliation reports missing/extra/changed.
- Export: roster CSV (injection-safe) and full organization export (hash-verified), both audited and capability-gated.
- Communications: unsubscribed excluded; critical suppression beats subscription; suppression after freeze still wins; required notices limited to fixed templates; inbound content cannot originate or approve; two-person approval bound to the exact audience hash; bounded retries.
- Backup/restore drill: pg_dump → fresh database → per-table count/digest, policies, triggers, constraints, sequences identical; RLS isolation and audit immutability re-verified in the restored copy; tampering detected.

## Not proven / not built (blocking Neon replacement)

- **Production activation** (owner-gated): migrations not applied to production; `OC_SOCIETY_CRM_API_ENABLED` off; backend login not yet granted `oc_crm_runtime`; runtime role discovery on Render/Neon not recorded.
- **Payments**: provider-neutral ledger and Stripe webhook adapter are in progress (#1656); creating live checkout sessions needs an owner-approved Stripe account and keys.
- **Outbound email provider**: no provider adapter or credentials; dispatch is tested with a test double only.
- **Provider restore**: the drill proves dump/restore fidelity, not Render/Neon point-in-time recovery; RPO/RTO unmeasured.
- **Frontend** (#871): no UI consumes these APIs yet.
- **Events** (#1658): not started.
- **Duplicate merge**: detection only.
- **Email change self-service** needs a verification flow.
- **FCOS shadow pilot, outside-society pilot, two non-developer administrators**: not started.
