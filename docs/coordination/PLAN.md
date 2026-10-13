# ACS-001 Implementation Plan

Goal: persistent agent assignments and reports without manual relay.
Architecture: independent Python package, transactional state machine, GitHub inbox/outbox and signed local ingress. SQLite local proof, optional psycopg PostgreSQL backend.
Spec: DESIGN.md. Execution: native in this session, per owner's independent-work instruction.

Global constraints: no Calyx imports, no ambient DATABASE_URL, no paid execution, no merges/deployments, no production DB access; no existing lane edits.
Review focus: concurrent claims; crash between GitHub POST and acknowledgement; stale tokens after retry; forged owner identity; gated action mislabeled as engineering. Engineering assignments do not execute arbitrary code, so the last failure cannot grant privileged execution through ACS.

1. State and persistence — coordination/store.py. Write failing unittest cases for restart, identical/conflicting events, one claim across two connections, fencing, heartbeat expiry, deadline, retries/dead letter and owner gates. Implement transactional acs_* schema and Store.apply(event, principal), Store.tick(), Store.take_report()/settle_report(). Verify via unittest discovery.
2. Transport — coordination/github.py and coordination/ingress.py. Tests for allowlisted numeric author IDs, unknown messages, pagination, stable marker reconciliation and signed-body tamper/expiry. Implement fixed-repository GitHub API client and inbox/outbox bridge. No workflow dispatch or provider adapter.
3. Runtime and runbook — coordination/__main__.py. Test the full fixture assignment/claim/heartbeat/response/report roundtrip; document CLI migration, recovery, PostgreSQL test requirements, agent adapters and owner activation checklist. Compile, diff-check, security guard, focused tests, attempt repo suite and record limitations.
4. Publish authoritative draft PR and hub evidence with exact commit, executed tests, unverified hosted/PostgreSQL status and concrete owner boundary. Do not merge or activate.
