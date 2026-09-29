# OC-SOCIETY-CRM-AGENT-PROMPT-001

Use this prompt with a high-capability coding agent.

## Mission

Build Orchid Continuum's Society CRM into a trustworthy, multi-tenant product without creating per-society forks or deployments.

Read first:
- docs/architecture/OC-SOCIETY-CRM-READINESS-001.md
- docs/architecture/OC-CONSTITUENT-PLATFORM-001.md
- migrations/20260823_oc_constituent_communications_foundation.sql
- app/constituent_platform/**
- app/member_auth.py
- docs/security/NEON_PARTNER_DATA_RLS_DEPLOYMENT_PLAN.md

Repository: jsp1440/orchid-calyx-backend
Companion frontend: jsp1440/orchid-continuum-frontend
Production hosting constraint: Render. Do not introduce Vercel.

## Non-negotiable architecture

One shared multi-tenant CRM, not one deployment per society.

Every society-owned record must be organization scoped. Cross-tenant access must fail closed. Society membership must never implicitly expose private Conservatory, OASIS, Calyx, research, donor, restricted locality, or collection data.

The canonical CRM source of truth must be explicit. Do not leave memberships in one schema while newsletter/member state silently lives in an unrelated generic store.

## Execution order

Work in independently mergeable slices, with tests before claiming completion.

1. Canonical persistence adapter for oc_constituent / oc_communications.
2. Tenant context, staff roles and authorization.
3. Database/service isolation and negative cross-tenant tests.
4. Membership-level catalog, member CRUD and lifecycle.
5. Append-only CRM audit trail.
6. CSV import/export with dry-run, idempotency, reconciliation and error report.
7. Renewal and dues ledger, including offline/check payments.
8. Payment-provider abstraction and one provider implementation; no card credentials in OC.
9. Donation ledger/receipts.
10. Member portal APIs.
11. Society event + registration APIs.
12. Communications adapter, bounce/suppression handling and approved sends.
13. Safe admin diagnostics.
14. Backup/restore verification harness.
15. Frontend society admin/member portal integration.

## Definition of done for every slice

- migrations are idempotent;
- existing tests remain green;
- new behavior has unit + integration tests;
- authorization is default-deny;
- cross-tenant negative tests are included where applicable;
- no secrets or payment credentials are stored in application tables;
- API errors are actionable but do not disclose another tenant's resource existence;
- retryable writes are idempotent;
- audit records are emitted for administrative mutations;
- public/member/admin surfaces are clearly separated;
- documentation states what is proven and what remains unproven.

## Required proof before calling CRM production-ready

Run synthetic two-tenant tests with overlapping member emails and prove:
- tenant A cannot read, mutate, search or export tenant B;
- member cannot elevate role;
- lapsed membership loses society-gated entitlements;
- imports are safely repeatable;
- duplicate webhooks do not duplicate money;
- backup/restore returns identical membership/payment/preference/audit state;
- no operator database edit is required for normal workflows.

Do not claim Neon replacement readiness until the FCOS shadow-pilot acceptance criteria in OC-SOCIETY-CRM-READINESS-001 are satisfied.

## Working style

Be relentless about completing one production slice at a time. Do not spend cycles on unrelated Orchid Continuum features while this mission is active. If a blocker is found, fix it when it is local and safe; otherwise create a narrowly scoped issue with reproduction evidence and continue on the next independent slice.

Prefer several small, reviewable PRs over one enormous PR. Each PR must state:
- user workflow delivered;
- migrations changed;
- endpoints changed;
- tests added;
- tenant-isolation proof;
- rollback considerations;
- remaining blockers.
