# BUILD-BRAIN-112A — Governed assignment creation and remediation intelligence

## Objective

Connect scheduler-authorized durable worker claims to deterministic `GovernedAssignment` creation so workers receive one checksum-verifiable execution contract instead of inventing provider-specific payloads.

## Implemented

- Added a governed assignment factory for live leased `CalyxProgramJob` rows.
- Assignment identity equals the durable `program_job_id`, preserving receipt and lease correlation.
- Included program objective, job role, repository, branch, mutating intent, attempt count, and explicit governance flags in canonical inputs.
- Granted only `validate_input`, `produce_receipt`, and `collect_evidence_uris` capabilities.
- Represented mutating work as intent data; it does not grant shell, network, merge, deployment, publication, credential, or graph-mutation authority.
- Added canonical input checksums and stable Calyx evidence URIs.
- Updated the protected worker claim route to return the claimed job and governed assignment together.
- Fixed an owner-isolation gap: authenticated worker claims and expired-lease recovery are now owner-scoped.
- Added tests for deterministic assignment payloads, safe capability bounds, owner isolation, live-lease enforcement, and scoped lease recovery.

## Governance

- Assignment creation does not execute work.
- External execution remains unauthorized.
- Automatic merge, deployment, publication, credential access, and production Knowledge Graph mutation remain false.
- Worker claims remain scheduler-authorized, atomic, and lease-backed.
- Receipt completion remains governed by BUILD-BRAIN-109.

## Operational chain

`persisted scheduler -> owner-scoped atomic claim -> governed assignment -> bounded executor -> verifiable receipt -> lease completion`

## Next bounded integration

Add exact assignment-blocker remediation summaries to Mission Control and a protected dry-run execution endpoint that accepts only the deterministic executor, requires a live owner-scoped lease, and records the resulting receipt without enabling external providers or production side effects.
