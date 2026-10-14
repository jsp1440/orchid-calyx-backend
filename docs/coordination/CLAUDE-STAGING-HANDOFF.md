# ACS-STAGING-PREFLIGHT-002: Claude adapter staging preflight and activation handoff

- **Assignment:** https://github.com/jsp1440/orchid-calyx-backend/pull/1836#issuecomment-6159437647 (follow-up: #issuecomment-6160292741)
- **Code:** `coordination/claude_staging.py`
- **Tests:** `tests/coordination/test_acs_claude_staging.py`
- **Base:** reviewed adapter head `ec5445ae227bc7dee9f76a56abba59c83ae717aa` (#1836). That builds on the coordinator at `65cf3f8687bd79d5438426ebcf55dd8e0614b4f2` (#1833). Neither reviewed module is modified.

Nothing in this change deploys, provisions, enables a setting, creates or reads a credential, or calls a model.

## 1. Remote wiring

`build_remote_adapter(RemoteConfig)` wires the reviewed adapter without changing it:

| Role | Component | Pinning |
|---|---|---|
| Claim / heartbeat / respond | `SignedIngressTransport` → staging edge `POST /events` | Agent-only HMAC key. The edge forwards only to loopback ingress. |
| Discovery | `ReportDiscovery` over `HubReader` | Reuses the coordinator's `GitHub` client, which is path-pinned to hub #1823. The reader can't post. |
| Results | `ResultPublisher` over `PullRequestComments` | Path-pinned to `jsp1440/orchid-calyx-backend` PR #1836 comments. Redirects are refused, responses are capped at 4 MiB, and pagination is capped. |
| Execution | `MockClaudeExecutor` | The only executor. `ExecutionPolicy()` defaults apply: live disabled, concurrency 1, engineering only. |

The adapter's existing fencing, dedup, outbox reconciliation and kill switch are reused unchanged.

### Fail-closed rules
- Any missing setting returns `BLOCKED` and lists the missing names.
- The stage must be `staging`.
- Ingress must be exactly `https://orchid-agent-coordinator-staging.onrender.com/events` (the `render.yaml` service; `STAGING_HOSTS` in code). Any other host, including staging-looking names, a non-443 port, a query, fragment or userinfo, is refused. If Render assigns a different hostname, adding it to `STAGING_HOSTS` is a reviewed code change, never a setting.
- Production targets are refused: `orchid-calyx-backend.onrender.com`, `orchid-continuum-frontend-vof6.onrender.com`, `orchid-continuum-public-api.onrender.com`, and `orchidcontinuum.org` with all its subdomains.
- Loopback is accepted only by the offline acceptance.
- The agent secret must be at least 32 characters.
- Any value reused across the agent secret, hub token and PR token is refused, including hub token = PR token.
- `--live` is refused.

## 2. Readiness report

```
python -m coordination.claude_staging readiness            # config only, no network
python -m coordination.claude_staging readiness --probe    # read-only probes of the configured target
```

The report uses schema `oc.acs-claude-readiness.v1`. Setting values are redacted: secret settings report presence only, and the ingress URL reports its host only.

Each item is reported separately:

| Section | Verified only when |
|---|---|
| `deployment_endpoint` | `GET https://<host>/healthz` returns 200 with `status: alive` and `stage: staging`. |
| `persistent_storage` | Never verified by this command. The staging bootstrap refuses to start without a mounted `/var/data`, but survival across restart needs an operator restart test. |
| `agent_ingress` | A signed heartbeat for a random nonexistent task returns exactly `400 {"error":"EVENT_REFUSED"}`. The coordinator authenticates first and rejects owner or unknown keys with 403. It then raises `TASK_NOT_FOUND` inside the transaction, so nothing is written. This is checked against the real coordinator in tests. |
| `reporter_authentication.hub_read` | Hub comments are read successfully. |
| `reporter_authentication.pr_write` | An adapter-marked comment from the PR reporter id is observed. Read access alone gives `read_verified_write_unverified`. |
| `executor` | Always `mock_only` / `live_runner: not_supported` in this code. |
| `receipt_result_evidence` | An adapter `RESULT` from the PR reporter id whose canonical payload names `executor: claude-live-runner`. Mock results, results from other authors and non-canonical payloads never count. |

`ready` is true only if every section is verified and `live_readiness` passes. With this code it is always `false`. That is the intended answer: there is no live runner, no restart proof and no distinct identity. A configured URL, a set variable, a skipped test or a fake-GitHub result never makes an item verified.

Probe failures are bounded and fail closed:
- A coordinator outage, refused connection, truncated body (`IncompleteRead`), non-JSON or non-object JSON, non-UTF-8 body or 5xx response marks that item `failed`. It never raises and never sets it verified.
- `/healthz` values are reported as booleans only (`status_alive`, `stage_staging`, `ready`). Raw response text is never echoed.
- Comment URLs appear only if they are links into PR #1836.
- Malformed PR comment items are ignored.
- `accept --mode staging` stops with `BLOCKED` before any adapter cycle when the endpoint or agent key is not verified.

## 3. Acceptance command

```
python -m coordination.claude_staging accept --mode offline
```

The offline mode runs the real coordinator `Store` and `Bridge`, real signed HTTP ingress on `127.0.0.1`, and in-memory fake GitHub. Its output is labelled `LOCAL_MOCK_PROOF`.

Scenarios:
1. `assignment_to_reconciled_result`: owner assignment on the hub, then report discovery, signed claim, heartbeats, bounded artifact and checks, signed response, PR receipt and result, and the coordinator `delivered` report. The evidence includes the per-kind counts of agent events written through signed ingress.
2. `restart_resumes_valid_lease`: the process dies mid-job, and the next process resumes with the stored lease (attempts stay at 1).
3. `kill_switch_cancels`: the kill switch is engaged mid-job, and the task responds `blocked`.
4. `ambiguous_post_reconciled`: the result POST response is lost, and the flush reconciles it without posting a duplicate.

```
python -m coordination.claude_staging accept --mode staging
```

The staging mode refuses `--live` (`REFUSED`), and refuses missing or invalid settings and production or loopback targets (`BLOCKED`). It runs the readiness probes and stops (`BLOCKED`) unless the endpoint and agent key are verified. It then runs exactly one adapter cycle with the mock executor, labelled `STAGING_COORDINATION_PATH_WITH_MOCK_EXECUTOR`.

The staging mode never creates assignments. An owner posts a staging test assignment through the coordinator first. Without one, the cycle claims nothing and says so.

Exit codes: 0 means passed or ran, 1 means the offline acceptance failed, and 2 means blocked or refused.

## 4. Activation handoff (owner / operator)

### Source and image
- **Coordinator service:** `deploy/coordination/render.yaml` defines `orchid-agent-coordinator-staging`. It builds `deploy/coordination/Dockerfile` (`python:3.12.15-slim`, `COPY coordination/`, `CMD python -m coordination.staging`) from branch `feat/agent-coordination-1823`, which is at `65cf3f8687bd79d5438426ebcf55dd8e0614b4f2` at the time of writing. `autoDeployTrigger: off`.
- No image has been built or pushed by this work, so no image digest exists to pin. The operator should deploy that exact commit and record the Render deploy id and image digest it reports.
- **Adapter:** this branch's head contains `coordination/claude_adapter.py` and `coordination/claude_staging.py`. The adapter runs in the Claude runner's environment, not in the coordinator service. It is not part of the coordinator image built from `feat/agent-coordination-1823`.

### Required settings (names only; none exists yet)

Coordinator (from `render.yaml`): `COORDINATOR_STAGE`, `COORDINATOR_INGRESS_KEYS` (must contain an `agent`/`claude` entry plus exactly one owner key), `COORDINATOR_GITHUB_TOKEN`, `COORDINATOR_PRINCIPALS`, `COORDINATOR_REPORTER_IDS`, `COORDINATOR_WEBHOOK_SECRET`.

Adapter runner: `ACS_CLAUDE_STAGE`, `ACS_CLAUDE_INGRESS_URL`, `ACS_CLAUDE_KEY_ID`, `ACS_CLAUDE_KEY_SECRET`, `ACS_CLAUDE_HUB_TOKEN`, `ACS_HUB_REPORTER_IDS`, `ACS_CLAUDE_PR_TOKEN`, `ACS_CLAUDE_PR_REPORTER_ID`, `ACS_CLAUDE_STATE_PATH`, `ACS_CLAUDE_WORKDIR`, `ACS_CLAUDE_KILL_SWITCH`.

`python -m coordination.claude_staging readiness` prints each setting's purpose.

### Operator steps (the order follows the independent review's gate list on #1836)
1. Deploy #1833 at the pinned commit to the staging service (owner action), then confirm `/healthz` reports `stage: staging`.
2. Issue an agent-only ingress key for `claude` in `COORDINATOR_INGRESS_KEYS`. Give its id and secret to the runner environment only.
3. Use a distinct GitHub identity for Claude results (not the shared `jsp1440` account). Set `ACS_CLAUDE_PR_REPORTER_ID` to its numeric id.
4. Issue a PR-scoped token for that identity (`ACS_CLAUDE_PR_TOKEN`) and a read-only hub token (`ACS_CLAUDE_HUB_TOKEN`).
5. Run `readiness --probe`. Expect `deployment_endpoint`, `agent_ingress` and `hub_read` to be verified, and `ready: false`.
6. Post one owner staging test assignment for `claude` (action `engineering`), then run `accept --mode staging`. A `delivered` cycle proves the coordination path with the mock executor. It does not prove Claude.
7. Restart the staging service. Confirm the task and event history survive, and record that as the persistent-storage evidence.
8. Only after a separate owner decision and a reviewed `ClaudeRunner` implementation: one observed live result. That remains out of scope here.

### Kill switch and rollback
- **Adapter:** create the file at `ACS_CLAUDE_KILL_SWITCH`. New claims stop, running work is cancelled, and the task responds `blocked`. Removing the file resumes.
- **Coordinator:** revoke the `claude` entry in `COORDINATOR_INGRESS_KEYS`. Every adapter call then gets 403 and fails closed. Or suspend the staging service; nothing else depends on it.
- **Rollback:** the adapter keeps its own SQLite state, and the coordinator stores its data on the staging disk only. Rolling back means stopping the runner and redeploying the previous staging commit. No production database, KG or service is involved.

## 5. Supported Claude-runner proposal

These facts were verified against official Claude Code documentation on 2026-10-14. Anything not stated in the docs is marked as such.

| Option | Wake | Auth | Lifetime | Billing / admin |
|---|---|---|---|---|
| **A. Claude Code GitHub Actions** ([docs](https://code.claude.com/docs/en/github-actions), [action](https://github.com/anthropics/claude-code-action)) | Automation mode (`prompt` input) on any GitHub event, including `schedule` and comment events. Interactive mode replies to `@claude`. | `ANTHROPIC_API_KEY`, or `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token` (Pro, Max, Team, Enterprise). OIDC workload identity and Bedrock/Vertex/Foundry are also supported. Without `github_token` it acts as the Claude GitHub App. | No Anthropic limit is stated. Bound it with `--max-turns` and workflow `timeout-minutes`. | API key: API token billing plus Actions minutes. OAuth token: draws on the subscription of whoever ran `setup-token`; the docs recommend an API key for shared org secrets. Schedules run from the default branch only. Write access is required for comment triggers, and bots are rejected unless listed in `allowed_bots`. |
| **B. Headless `claude -p` on an operator host** ([docs](https://code.claude.com/docs/en/headless), [auth](https://code.claude.com/docs/en/authentication)) | Not provided. The operator supplies the scheduler; the docs prescribe none. | `ANTHROPIC_API_KEY` is always used in `-p` when present. `--bare` requires an API key or `apiKeyHelper`. `setup-token` is documented for "CI pipelines and scripts". The docs do not say explicitly whether unattended subscription use is permitted; check the consumer terms before relying on it. | Exit code is 0 or non-zero, and SIGTERM gives 143. | `total_cost_usd` in JSON output is a client-side estimate. |
| **C. Routines** ([docs](https://code.claude.com/docs/en/routines)) | Schedule (hourly minimum), API fire (`POST …/v1/claude_code/routines/<id>/fire`, beta header; "not part of the Claude Platform API surface"), or GitHub PR/release events. | The creator's claude.ai account. Not available with a Console API key. | No maximum documented. A routine stops if the GitHub connection is missing for 72 h. | Research preview. Draws subscription usage like interactive sessions. Hourly caps are 100 scheduled runs per account, 30 per routine for run-now/API, and 100 API fires per account. **Off for this organization** (observed 2026-10-14); a Team/Enterprise owner toggles it at claude.ai admin settings → Claude Code. |
| **D. This session's PR subscription** (current, [docs](https://code.claude.com/docs/en/claude-code-on-the-web)) | PR comments, reviews and CI events on subscribed PRs | The session's subscription credentials | Ends when the session ends or is reclaimed after inactivity. Lifetime is not documented. | Plan usage. Interactive only, so it is not an unattended runner. |

**Recommendation:** use option A with a dedicated `ANTHROPIC_API_KEY` (metered and attributable) in the staging environment.

The runner would be a workflow that runs `python -m coordination.claude_staging accept --mode staging`, and only later a reviewed `ClaudeRunner` that calls `claude -p` with `--max-turns` and `--permission-mode dontAsk` plus an explicit `--allowedTools` list, under a workflow `timeout-minutes`. Triggers would be `schedule` (and, optionally, coordinator report comments). The runner should keep the adapter's concurrency of 1 and its daily budget. The adapter-side `ACS_CLAUDE_*` settings go in a protected staging environment.

Owner decisions required before any of this happens:
- creating or funding the API key, or choosing subscription OAuth instead;
- installing or authorizing the Claude GitHub App or a distinct bot identity;
- adding the workflow;
- enabling Routines, if option C is preferred.

None was taken here, and this change adds no workflow.
