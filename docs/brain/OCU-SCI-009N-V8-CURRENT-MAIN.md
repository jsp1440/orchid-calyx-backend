# OCU-SCI-009N v8 — current-main refresh

Refreshed the guarded Orchid University durable-session migration runner onto backend main `6cdeb43d462d52a4cab3f11056c72a290dfb9a01` after the previous authoritative draft drifted far behind.

Scope remains engineering-only and non-production:
- guarded transactional migration runner;
- exact migration SHA-256 and exact database-target confirmation;
- advisory-lock concurrency protection;
- bounded connect/lock/statement timeouts;
- NOT NULL plus constraint verification;
- PostgreSQL apply/rollback tests;
- Durable Foundation integration.

This refresh does not apply any production migration, enable University session writes/durable mode, assign reviewer qualifications, publish science, promote Candidate Knowledge, or mutate taxonomy/Knowledge Graph state.
