# ACS-001 operator and agent runbook

The coordinator is implemented for review. It is not deployed, no real agent is subscribed, and no provider execution is enabled. Hub: https://github.com/jsp1440/orchid-calyx-backend/issues/1823.

## Run locally, without network or credentials

```bash
python -B -m unittest discover -s tests/coordination -v
python -m coordination init --sqlite-path /tmp/acs-demo.db
python -m coordination health --sqlite-path /tmp/acs-demo.db
```

Core/runtime use Python 3.12 stdlib. PostgreSQL additionally requires the existing project's psycopg driver (CI pins psycopg[binary] 3.3.6). Runtime never reads DATABASE_URL, imports Calyx or creates tables on startup. Core tests need no network. Local HTTP tests bind only loopback. PostgreSQL tests skip without ACS_TEST_POSTGRES_URL; the workflow supplies a disposable PostgreSQL 16 service and must execute all four database tests.

## Operator configuration after approved activation

- COORDINATOR_DATABASE_URL: dedicated PostgreSQL connection with authority on acs_* tables only. For LISTEN/NOTIFY extensions later use a direct URL; this version uses webhook wakeups, not LISTEN.
- Alternatively --sqlite-path: absolute path on persistent disk. Never use an ephemeral Render path or GitHub runner file for live state. Multiple hosts require PostgreSQL.
- COORDINATOR_GITHUB_TOKEN: repository-scoped token with issues read/write; no contents/actions/admin access needed by runtime.
- COORDINATOR_PRINCIPALS: JSON map of numeric GitHub user IDs to {role, name}. Roles are owner, coordinator or agent. Agents: chatgpt, claude, kimi, copilot, calyx. One account has one role, never infer a role from a comment claiming “I am Claude.”
- COORDINATOR_REPORTER_IDS: JSON array of verified numeric IDs for the reporter's token. Wrong configuration fails report reconciliation; never guess or use arbitrary bot authors.
- COORDINATOR_INGRESS_KEYS: private JSON map key IDs to {secret, role, name}; independent >=32-character random secrets for each identity. Owner key must never be given to an agent. No keys committed to GitHub.
- COORDINATOR_WEBHOOK_SECRET: optional private >=32-character GitHub webhook secret. Register issue_comment.created events against a TLS proxy's /github/events endpoint only after owner authorization.

Explicit schema setup: `python -m coordination init --confirm-isolated-postgres` with approved dedicated URL. This flag is operator acknowledgement, not a programmatic check that a database is non-production. Verify the connection before running it. Do not use the inspected Neon production branch.

Start command: `python -m coordination run --port 8765 --interval 60`. It starts a loopback ingress server and an outbound reporter. A private authenticated TLS reverse proxy is required for remote ingress; there is deliberately no public plaintext binding flag. `once` performs one bounded GitHub reconciliation. SIGTERM/SIGINT stop the process; unfinished leases are recovered on restart. Use `health` to inspect unknown/healthy/stale agent observations.

## Agent GitHub protocol

A message is exactly the prefix [OC-ACS-v1], followed by one json fence containing a v1 event. Send immutable comments; edits are refused once observed. Use a fresh stable event_id for each action, keeping the same id when retrying an uncertain submission. Do not put secrets, locality data, arbitrary prompt text or transcripts into this hub.

Example assignment (submitted by configured owner/coordinator identity):

````text
[OC-ACS-v1]
```json
{"version":1,"event_id":"acs-example-assign-001","kind":"assign","task_id":"acs-example-001","agent":"claude","action":"engineering","objective":"https://github.com/jsp1440/orchid-calyx-backend/issues/1823"}
```
````

The outer text fence above is illustrative; post only the prefix and inner JSON fence. Agents read assignments addressed to their configured identity, claim using kind=claim with the four common fields, then read the report's attempt count. Heartbeat and response comments add attempt (integer); responses also add outcome (delivered or blocked) and reference (canonical issue/PR URL). A response is a maker report, not independent checker acceptance. Comments authenticated as the wrong agent cannot settle a task. Public comments must never carry lease_token.

A GitHub-reading agent session must already be running, or have an independently authorized wake-up adapter. This runtime does not call Claude/Kimi/ChatGPT consumer sessions or Copilot assignment APIs. Kimi or Copilot capability must be verified before automatic subscription; an account subscription does not prove callable background execution. Polling only the hub does not make another agent work.

## Signed private API and later Calyx integration

POST /events accepts the same events. Headers: X-ACS-Key, X-ACS-Time (Unix seconds), X-ACS-Signature (hex HMAC-SHA256 over timestamp + '.' + exact body bytes). Timestamp tolerance is 300 seconds. Duplicate event IDs are durable receipts; a changed payload under the same ID is refused. Claim returns a private lease_token. Private heartbeat/response must carry that token; attempt-only private events are refused.

Calyx's later adapter obtains an agent-only key, reads its assignments, signs claim/heartbeat/response events and preserves the canonical issue/PR evidence reference. No Calyx code or database imports are needed. Agent adapters execute safe work outside ACS and remain responsible for sandbox, permissions, costs and owner gates. Engineering is a label for routing, not blanket permission to execute the objective's external text.

## Recovery and decisions

- Default heartbeat lease: 60 seconds. Send every 20–30 seconds while work is genuinely active. Hard attempt deadline: 900 seconds. Split longer work into bounded tasks; do not fabricate heartbeats.
- Timeouts retry with 10/20/40 second exponential delays, capped at 300 seconds. Three claims maximum; then task dead_letter. Report retries separately have three delivery attempts and expiring report leases.
- Outbox detects an uncertain previous POST by exact body plus stable marker from verified reporter identity. Exactly-once GitHub POST is not promised; event deduplication protects consumers.
- Invalid/unauthorized comments are recorded as rejected in acs_inbox; they never silently become executable on a later poll. To correct a refused message, send a new comment/event ID.
- Gate actions: merge, deploy, production_db, paid_ai, infrastructure, scientific_publish. Owner approve/reject events bind exact task digest; approval expires in at most 24 hours. Approved gates remain unclaimable because this version has no privileged executor. Activate privileged work only through separately approved systems.
- Reporter omits objective URLs, response references, tokens and transcripts; full canonical response reference remains in task state and in the submitted GitHub response comment.
- GitHub outages do not prevent local lease expiry. Failed cycles print fixed reason codes, without exception strings that may reveal credentials.
- More than 10,000 hub comments fails closed with GITHUB_COMMENT_LIMIT_REACHED rather than incomplete deduplication. Archive/rotation support needs a later bounded transport extension before that volume.

## Essential activation gates

Independent review on exact head; chosen persistent host and isolated schema; verified least-privilege reporter identity; separate agent identities/keys; authenticated TLS webhook/proxy; live adapter reachability proof. The current owner-authored PRs do not establish distinct agent GitHub accounts. If agents share jsp1440, use distinct signed keys and do not allowlist that account simultaneously as owner and agent.

Existing suspended acceptance worker belongs to the Calyx autonomy acceptance lane. Repointing it would interrupt that lane and is not authorized by this implementation. Existing Calyx production service auto-deploys main; this PR does not touch its entry point or deployment configuration. Do not resume, repoint, provision or change production schema merely to make this coordinator live.

Rollback: stop coordinator/proxy ingress. Preserve acs_* audit data; do not delete it automatically. Scientific schemas, existing scheduler, providers and other agent branches remain unchanged by the implementation.
