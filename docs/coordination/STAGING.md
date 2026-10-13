# Authorized ACS staging pilot

Owner authorized the separate Render staging pilot and distinct scoped credentials on 2026-10-13. Authorization covers the proposed 512 MB web process and 1 GB persistent SQLite disk ($7.25/month base before usage/workspace/tax charges); no paid AI execution, production mutations or merges.

## Deployment design
- Dedicated service orchid-agent-coordinator-staging, Oregon, canonical repo, existing feat/agent-coordination-1823 branch. Auto-deploy off, no default-main dependency.
- Self-contained Docker context limited to coordination runtime and deployment files. Render's TLS edge forwards to a bounded Python proxy on PORT; proxy forwards only /events and /github/events to loopback authenticated ingress. /healthz reveals liveness and configuration readiness only, never tasks or keys. No arbitrary upstream destinations.
- Staging bootstrap requires COORDINATOR_STAGE=staging, a real /var/data mount and no PostgreSQL URL. Initializes acs_* only on the dedicated local disk under restrictive umask. No production database connectivity.
- Separate HMAC keys: one owner; five agent-only identities; optional GitHub webhook secret. No shared owner/agent credential. No secrets in source, build args, public docs or logs.
- GitHub reporter: fine-grained token restricted to jsp1440/orchid-calyx-backend with issues read/write. No contents, actions, administration, merge or production authority. Until this credential and verified numeric identity bindings are configured, service may report alive but not ready; no GitHub polling/reporting occurs.
- This pilot enables transport only. Agent execution adapters remain unconfigured until each is authenticated and tested; it cannot wake arbitrary consumer chat sessions or invoke model providers.

## Connector limitations observed
Render MCP create_web_service has no disk parameter or disk-attach operation. GitHub MCP has no token creation endpoint. No authenticated CLI credentials are present locally. Do not provision a paid service with an ephemeral substitute, reuse production secrets, or broaden token permissions to work around these omissions. Browser access to the authorized accounts is the remaining setup path and requires the harness's separate browser-fallback permission.

## Validation plan
Test public proxy allowlist/forwarding/signature preservation, unauthenticated refusal, bounded bodies, safe health projection, bootstrap refusal without a real disk, staging-only schema guard, and duplicate owner/agent credential rejection. CI builds the isolated Docker image and tests the bootstrap/edge on disposable container storage marked test-only; it never provisions Render or supplies live credentials. Runtime acceptance later: disk visible in Render metadata, deployed exact SHA, TLS health plus readiness, signature tamper rejection, persisted task after process restart, GitHub report evidence and no provider execution.
