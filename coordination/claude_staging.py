"""Staging preflight, readiness and acceptance for the Claude ACS adapter (ACS-STAGING-PREFLIGHT-002).

The reviewed adapter CLI (``python -m coordination.claude_adapter``) wires only
the in-process ``StoreTransport`` and a result publisher that fails closed. This
module adds the remote wiring, without changing the reviewed adapter:

* ``SignedIngressTransport`` (agent-only HMAC key) to the staging edge ``/events``;
* ``ReportDiscovery`` over the hub's coordinator reports (read-only hub client);
* ``ResultPublisher`` over a PR-comments client pinned to this repository and PR.

The mock executor stays the only executor. Missing settings, production
targets and live-runner requests fail closed. Readiness is computed from probe
evidence, never from configuration presence: a configured URL, a set variable,
a skipped test or a fake-GitHub result never makes a section ``verified``.
Secrets are never printed; the report names settings only.

Commands::

    python -m coordination.claude_staging readiness [--probe]
    python -m coordination.claude_staging accept --mode offline
    python -m coordination.claude_staging accept --mode staging
"""

from __future__ import annotations

import json
import re
import secrets
import tempfile
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .claude_adapter import (
    ADAPTER_MARKER,
    RESULT_PREFIX,
    AdapterState,
    ClaudeAdapter,
    ExecutionPolicy,
    MockClaudeExecutor,
    ReportDiscovery,
    ResultPublisher,
    SignedIngressTransport,
    live_readiness,
)
from .github import REPOSITORY, GitHub, NoRedirect, strict_json
from .store import canonical

PINNED_REPOSITORY = REPOSITORY  # "jsp1440/orchid-calyx-backend"
PINNED_RESULT_PR = 1836
STAGE = "staging"
OFFLINE_LABEL = "LOCAL_MOCK_PROOF: offline fakes and a loopback coordinator; not staging or production evidence"
STAGING_LABEL = "STAGING_COORDINATION_PATH_WITH_MOCK_EXECUTOR: no live Claude execution"

#: Known production / public hosts in this repository's configuration. Staging mode refuses them.
PRODUCTION_HOSTS = frozenset(
    {
        "orchid-calyx-backend.onrender.com",
        "orchid-continuum-frontend-vof6.onrender.com",
        "orchid-continuum-public-api.onrender.com",
    }
)
PRODUCTION_SUFFIXES = (".orchidcontinuum.org",)


@dataclass(frozen=True)
class Setting:
    name: str
    secret: bool
    purpose: str


#: Required settings, by name only. Values are supplied by the operator; none is created here.
SETTINGS = (
    Setting("ACS_CLAUDE_STAGE", False, "must be exactly 'staging'"),
    Setting(
        "ACS_CLAUDE_INGRESS_URL",
        False,
        "staging edge URL ending in /events (https, staging host)",
    ),
    Setting(
        "ACS_CLAUDE_KEY_ID", False, "agent-only ingress key id issued for 'claude'"
    ),
    Setting(
        "ACS_CLAUDE_KEY_SECRET",
        True,
        "agent-only HMAC secret for that key id (>= 32 chars)",
    ),
    Setting(
        "ACS_CLAUDE_HUB_TOKEN",
        True,
        "read-only token for hub #1823 comments (report discovery)",
    ),
    Setting(
        "ACS_HUB_REPORTER_IDS",
        False,
        "JSON list of GitHub user ids that post coordinator reports",
    ),
    Setting(
        "ACS_CLAUDE_PR_TOKEN",
        True,
        f"token that may read/write comments on PR #{PINNED_RESULT_PR}",
    ),
    Setting(
        "ACS_CLAUDE_PR_REPORTER_ID",
        False,
        "GitHub user id that ACS_CLAUDE_PR_TOKEN posts as",
    ),
    Setting("ACS_CLAUDE_STATE_PATH", False, "persistent adapter SQLite file"),
    Setting("ACS_CLAUDE_WORKDIR", False, "directory for bounded mock artifacts"),
    Setting("ACS_CLAUDE_KILL_SWITCH", False, "file path whose existence stops claims"),
)


class StagingConfigError(ValueError):
    pass


def check_target(url: str, *, allow_loopback: bool) -> str:
    """Return the host of an acceptable ingress URL, or raise. Refuses production targets."""
    parts = urlsplit(url or "")
    host = (parts.hostname or "").lower()
    if (
        parts.path != "/events"
        or parts.query
        or parts.fragment
        or parts.username
        or parts.password
    ):
        raise StagingConfigError("INGRESS_URL_MUST_BE_BARE_EVENTS_PATH")
    if host == "127.0.0.1" and parts.scheme == "http":
        if not allow_loopback:
            raise StagingConfigError("LOOPBACK_NOT_A_STAGING_TARGET")
        return host
    if parts.scheme != "https" or not host:
        raise StagingConfigError("INGRESS_MUST_BE_HTTPS")
    if host in PRODUCTION_HOSTS or any(
        host.endswith(s) or host == s.lstrip(".") for s in PRODUCTION_SUFFIXES
    ):
        raise StagingConfigError("PRODUCTION_TARGET_REFUSED")
    if "staging" not in host.split(".")[0]:
        raise StagingConfigError("TARGET_NOT_IDENTIFIED_AS_STAGING")
    return host


@dataclass(frozen=True)
class RemoteConfig:
    ingress_url: str
    host: str
    key_id: str
    key_secret: str
    hub_token: str
    hub_reporter_ids: frozenset
    pr_token: str
    pr_reporter_id: int
    state_path: str
    workdir: str
    kill_switch: str

    @property
    def result_ref(self) -> str:
        return f"https://github.com/{PINNED_REPOSITORY}/pull/{PINNED_RESULT_PR}"

    @classmethod
    def from_env(cls, env, *, allow_loopback: bool = False):
        """Return ``(config_or_None, missing_names, error_codes)``; never raises on bad input."""
        missing = [s.name for s in SETTINGS if not env.get(s.name)]
        errors: list = []
        if env.get("ACS_CLAUDE_STAGE") and env.get("ACS_CLAUDE_STAGE") != STAGE:
            errors.append("STAGE_NOT_STAGING")
        host = ""
        if env.get("ACS_CLAUDE_INGRESS_URL"):
            try:
                host = check_target(
                    env["ACS_CLAUDE_INGRESS_URL"], allow_loopback=allow_loopback
                )
            except StagingConfigError as exc:
                errors.append(str(exc))
        if env.get("ACS_CLAUDE_KEY_SECRET") and len(env["ACS_CLAUDE_KEY_SECRET"]) < 32:
            errors.append("AGENT_KEY_TOO_SHORT")
        hub_ids: frozenset = frozenset()
        if env.get("ACS_HUB_REPORTER_IDS"):
            try:
                parsed = strict_json(env["ACS_HUB_REPORTER_IDS"])
                if (
                    not isinstance(parsed, list)
                    or not parsed
                    or any(type(i) is not int or i < 1 for i in parsed)
                ):
                    raise ValueError
                hub_ids = frozenset(parsed)
            except ValueError:
                errors.append("HUB_REPORTER_IDS_INVALID")
        pr_id = 0
        if env.get("ACS_CLAUDE_PR_REPORTER_ID"):
            try:
                pr_id = int(env["ACS_CLAUDE_PR_REPORTER_ID"])
                if pr_id < 1:
                    raise ValueError
            except ValueError:
                errors.append("PR_REPORTER_ID_INVALID")
        if env.get("ACS_CLAUDE_KEY_SECRET") and env.get("ACS_CLAUDE_KEY_SECRET") in {
            env.get("ACS_CLAUDE_HUB_TOKEN"),
            env.get("ACS_CLAUDE_PR_TOKEN"),
        }:
            errors.append("CREDENTIAL_REUSED_ACROSS_ROLES")
        if missing or errors:
            return None, missing, errors
        return (
            cls(
                ingress_url=env["ACS_CLAUDE_INGRESS_URL"],
                host=host,
                key_id=env["ACS_CLAUDE_KEY_ID"],
                key_secret=env["ACS_CLAUDE_KEY_SECRET"],
                hub_token=env["ACS_CLAUDE_HUB_TOKEN"],
                hub_reporter_ids=hub_ids,
                pr_token=env["ACS_CLAUDE_PR_TOKEN"],
                pr_reporter_id=pr_id,
                state_path=env["ACS_CLAUDE_STATE_PATH"],
                workdir=env["ACS_CLAUDE_WORKDIR"],
                kill_switch=env["ACS_CLAUDE_KILL_SWITCH"],
            ),
            [],
            [],
        )


def redacted_settings(env) -> dict:
    """Setting names with presence only; secret values are never included."""
    out = {}
    for s in SETTINGS:
        entry = {"set": bool(env.get(s.name)), "secret": s.secret, "purpose": s.purpose}
        if not s.secret and s.name in {
            "ACS_CLAUDE_STAGE",
            "ACS_HUB_REPORTER_IDS",
            "ACS_CLAUDE_PR_REPORTER_ID",
        }:
            entry["value"] = env.get(s.name) or None
        if s.name == "ACS_CLAUDE_INGRESS_URL" and env.get(s.name):
            entry["host"] = (urlsplit(env[s.name]).hostname or "").lower()
        out[s.name] = entry
    return out


# ---------------------------------------------------------------------------
# GitHub clients pinned to this repository
# ---------------------------------------------------------------------------


class PullRequestComments:
    """Comments of exactly one PR in the pinned repository (read and post)."""

    def __init__(self, token: str, *, pr: int = PINNED_RESULT_PR, opener=None):
        if not token or type(pr) is not int or pr < 1:
            raise ValueError("PR_CLIENT_CONFIG_REQUIRED")
        self.token, self.pr = token, pr
        self.base = f"/repos/{PINNED_REPOSITORY}/issues/{pr}/comments"
        self.opener = opener or urllib.request.build_opener(NoRedirect())

    def request(self, method: str, path: str, body=None):
        if not path.startswith(self.base):
            raise PermissionError("GITHUB_PATH_REFUSED")
        req = urllib.request.Request(
            "https://api.github.com" + path,
            data=None if body is None else json.dumps(body).encode(),
            method=method,
            headers={
                "Authorization": "Bearer " + self.token,
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "OC-ACS-claude-adapter",
            },
        )
        with self.opener.open(req, timeout=20) as resp:
            payload = resp.read(4 * 1024 * 1024 + 1)
        if len(payload) > 4 * 1024 * 1024:
            raise ValueError("GITHUB_RESPONSE_TOO_LARGE")
        return strict_json(payload)

    def comments(self) -> list:
        out = []
        for page in range(1, 101):
            batch = self.request("GET", f"{self.base}?per_page=100&page={page}")
            if not isinstance(batch, list):
                raise TypeError("GITHUB_RESPONSE_INVALID")
            out.extend(batch)
            if len(batch) < 100:
                return out
        raise ValueError("GITHUB_COMMENT_LIMIT_REACHED")

    def post(self, body: str):
        return self.request("POST", self.base, {"body": body})


class HubReader:
    """Read-only view of hub #1823 through the coordinator's own pinned client."""

    def __init__(self, token: str, reporter_ids, *, client=None):
        self.client = client or GitHub(token, reporter_ids=reporter_ids)

    def comments(self) -> list:
        return self.client.comments()

    def post(self, body):  # pragma: no cover - guard
        raise PermissionError("ADAPTER_NEVER_POSTS_TO_HUB")


def build_remote_adapter(
    config: RemoteConfig,
    *,
    hub_client=None,
    pr_client=None,
    opener=None,
    clock=time.time,
) -> ClaudeAdapter:
    """Wire the reviewed adapter for remote operation; mock executor only."""
    discovery = ReportDiscovery(
        hub_client or HubReader(config.hub_token, config.hub_reporter_ids),
        config.hub_reporter_ids,
    )
    transport = SignedIngressTransport(
        config.ingress_url,
        config.key_id,
        config.key_secret,
        discovery,
        opener=opener,
        clock=time.time,
    )
    state = AdapterState(config.state_path, clock=clock)
    publisher = ResultPublisher(
        pr_client or PullRequestComments(config.pr_token),
        {config.pr_reporter_id},
        state,
    )
    return ClaudeAdapter(
        transport=transport,
        executor=MockClaudeExecutor(),
        state=state,
        publisher=publisher,
        canonical_ref=config.result_ref,
        workdir=Path(config.workdir),
        policy=ExecutionPolicy(),
        kill_switch=Path(config.kill_switch),
        clock=clock,
    )


# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------


def _http(opener, req):
    try:
        with opener.open(req, timeout=15) as resp:
            return resp.status, resp.read(65536)
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, exc.read(65536)
        except OSError:
            return exc.code, b""
    except (OSError, ValueError):
        return None, b""


def _probe_health(opener, host: str) -> dict:
    status, body = _http(
        opener, urllib.request.Request(f"https://{host}/healthz", method="GET")
    )
    try:
        data = strict_json(body) if body else {}
    except ValueError:
        data = {}
    ok = status == 200 and data.get("status") == "alive" and data.get("stage") == STAGE
    return {
        "status": "verified" if ok else "failed",
        "http_status": status,
        "observed": {k: data.get(k) for k in ("status", "stage", "ready")}
        if data
        else None,
    }


def _probe_ingress(opener, config: RemoteConfig) -> dict:
    """Signed heartbeat for a random, nonexistent task.

    The coordinator authenticates the signature first, then refuses the event
    (TASK_NOT_FOUND -> HTTP 400) before writing anything. 400 therefore proves
    the agent key is accepted without changing state; 403 means it is not.
    """
    import hashlib
    import hmac

    event = {
        "version": 1,
        "event_id": "preflight." + secrets.token_hex(8),
        "task_id": "preflight-" + secrets.token_hex(8),
        "kind": "heartbeat",
        "lease_token": secrets.token_hex(32),
    }
    body = canonical(event).encode()
    ts = f"{time.time():.3f}"
    sig = hmac.new(
        config.key_secret.encode(), ts.encode() + b"." + body, hashlib.sha256
    ).hexdigest()
    req = urllib.request.Request(
        config.ingress_url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-ACS-Key": config.key_id,
            "X-ACS-Time": ts,
            "X-ACS-Signature": sig,
        },
    )
    status, body = _http(opener, req)
    try:
        refused = strict_json(body) == {"error": "EVENT_REFUSED"}
    except ValueError:
        refused = False
    return {
        "status": "verified" if status == 400 and refused else "failed",
        "http_status": status,
        "method": "signed heartbeat for a nonexistent task; refused before any write",
        "proves": "signature accepted and principal role is agent (an owner or unknown "
        "key gets 403); the agent name is checked only against a real task",
    }


LIVE_EXECUTOR = "claude-live-runner"


def _live_result(body: str) -> bool:
    """True only for an adapter RESULT whose canonical payload names the live runner."""
    match = re.search(r"```json\n(.*)\n```\Z", body, re.DOTALL)
    if not match or f"{RESULT_PREFIX} RESULT:" not in body:
        return False
    try:
        payload = strict_json(match.group(1))
    except ValueError:
        return False
    return (
        isinstance(payload, dict)
        and payload.get("type") == "RESULT"
        and payload.get("executor") == LIVE_EXECUTOR
        and canonical(payload) == match.group(1)
    )


def readiness_report(
    env, *, probe: bool = False, opener=None, hub_client=None, pr_client=None
) -> dict:
    config, missing, errors = RemoteConfig.from_env(env)
    opener = opener or urllib.request.build_opener(NoRedirect())
    configured = config is not None

    def base(status, **extra):
        return {"status": status, **extra}

    sections = {
        "deployment_endpoint": base(
            "missing"
            if "ACS_CLAUDE_INGRESS_URL" in missing
            else ("configured_unverified" if configured else "invalid"),
            target=config.host if configured else None,
        ),
        "persistent_storage": base(
            "unverified_requires_restart_proof",
            note="The staging bootstrap refuses to start without a mounted disk, so a staging "
            "/healthz implies a mount at boot; continuity across restart is proven only "
            "by an operator restart test, which this command cannot perform.",
        ),
        "agent_ingress": base(
            "missing"
            if {"ACS_CLAUDE_KEY_ID", "ACS_CLAUDE_KEY_SECRET"} & set(missing)
            else ("configured_unverified" if configured else "invalid")
        ),
        "reporter_authentication": {
            "hub_read": base(
                "missing"
                if "ACS_CLAUDE_HUB_TOKEN" in missing
                else ("configured_unverified" if configured else "invalid")
            ),
            "pr_write": base(
                "missing"
                if "ACS_CLAUDE_PR_TOKEN" in missing
                else ("configured_unverified" if configured else "invalid")
            ),
        },
        "executor": base(
            "mock_only",
            live_runner="not_supported",
            note="MockClaudeExecutor is the only executor; ClaudeRunner refuses to start.",
        ),
        "receipt_result_evidence": base(
            "absent",
            note="needs an adapter RESULT from a live (non-mock) executor, "
            "observed on the pinned PR from the PR reporter id",
        ),
    }
    if probe and configured:
        sections["deployment_endpoint"] = {
            **_probe_health(opener, config.host),
            "target": config.host,
        }
        sections["agent_ingress"] = _probe_ingress(opener, config)
        try:
            (
                hub_client or HubReader(config.hub_token, config.hub_reporter_ids)
            ).comments()
            sections["reporter_authentication"]["hub_read"] = base("read_verified")
        except (OSError, ValueError, TypeError, PermissionError):
            sections["reporter_authentication"]["hub_read"] = base("failed")
        try:
            prc = pr_client or PullRequestComments(config.pr_token)
            comments = prc.comments()
            ours = [
                c
                for c in comments
                if c.get("user", {}).get("id") == config.pr_reporter_id
                and (c.get("body") or "").startswith(f"<!-- {ADAPTER_MARKER}:")
            ]
            sections["reporter_authentication"]["pr_write"] = (
                base(
                    "verified_by_observed_comment",
                    comment_url=ours[-1].get("html_url"),
                    note="an adapter comment from the PR reporter id exists; the token-to-id "
                    "binding is enforced at publish time (unreconciled posts dead-letter)",
                )
                if ours
                else base("read_verified_write_unverified")
            )
            live = [c for c in ours if _live_result(c.get("body") or "")]
            if live:
                sections["receipt_result_evidence"] = base(
                    "verified", comment_url=live[-1].get("html_url")
                )
        except (OSError, ValueError, TypeError, PermissionError):
            sections["reporter_authentication"]["pr_write"] = base("failed")
    statuses = [
        sections["deployment_endpoint"]["status"] == "verified",
        sections["persistent_storage"]["status"] == "verified",
        sections["agent_ingress"]["status"] == "verified",
        sections["reporter_authentication"]["hub_read"]["status"] == "read_verified",
        sections["reporter_authentication"]["pr_write"]["status"]
        == "verified_by_observed_comment",
        sections["executor"]["live_runner"] == "supported",
        sections["receipt_result_evidence"]["status"] == "verified",
    ]
    readiness = live_readiness(
        agent_key_configured=sections["agent_ingress"]["status"] == "verified",
        runner_configured=sections["executor"]["live_runner"] == "supported",
        distinct_identity=False,
        observed_live_result_url=sections["receipt_result_evidence"].get("comment_url"),
    )
    return {
        "schema": "oc.acs-claude-readiness.v1",
        "ready": all(statuses) and readiness["ready"],
        "probed": bool(probe and configured),
        "missing_settings": missing,
        "config_errors": errors,
        "settings": redacted_settings(env),
        "sections": sections,
        "unattended_gates_missing": readiness["missing"],
        "note": "Configuration presence, skipped tests and fake-GitHub results never count as verified.",
    }


# ---------------------------------------------------------------------------
# Acceptance
# ---------------------------------------------------------------------------


class _FakeComments:
    def __init__(self, author: int):
        self.items, self.author, self.fail_after_post = [], author, False

    def comments(self):
        return list(self.items)

    def add(self, body, user):
        self.items.append(
            {"id": len(self.items) + 1, "body": body, "user": {"id": user}}
        )

    def post(self, body):
        self.add(body, self.author)
        if self.fail_after_post:
            self.fail_after_post = False
            raise TimeoutError("RESPONSE_LOST")


def offline_acceptance(root: Path | None = None) -> dict:
    """Assignment -> claim -> heartbeat -> artifact/checks -> response -> reconciled result,
    plus restart, cancellation and ambiguous-POST cases, through the remote wiring."""
    from .github import Bridge
    from .ingress import make_server
    from .store import Principal, Store

    owner, reporter, pr_reporter = 1, 99, 77
    hub_ref = f"https://github.com/{PINNED_REPOSITORY}/issues/1823"
    scenarios = []
    with tempfile.TemporaryDirectory(dir=root) as tmp:
        base = Path(tmp)
        clock = [1000.0]
        store = Store(str(base / "acs.db"), clock=lambda: clock[0])
        store.initialize()
        hub = _FakeComments(reporter)
        hub.reporter_ids = {reporter}
        bridge = Bridge(store, hub, {owner: Principal("owner", "owner")})
        secret = secrets.token_hex(32)
        server = make_server(
            store,
            {"claude-preflight": {"secret": secret, "role": "agent", "name": "claude"}},
            port=0,
        )
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:

            def assign(task_id):
                event = {
                    "version": 1,
                    "event_id": f"assign-{task_id}",
                    "task_id": task_id,
                    "kind": "assign",
                    "agent": "claude",
                    "action": "engineering",
                    "objective": hub_ref,
                }
                hub.add("[OC-ACS-v1]\n```json\n" + json.dumps(event) + "\n```", owner)
                bridge.cycle()

            def adapter(name, pr, executor=None):
                config = RemoteConfig(
                    ingress_url=f"http://127.0.0.1:{server.server_address[1]}/events",
                    host="127.0.0.1",
                    key_id="claude-preflight",
                    key_secret=secret,
                    hub_token="offline",
                    hub_reporter_ids=frozenset({reporter}),
                    pr_token="offline",
                    pr_reporter_id=pr_reporter,
                    state_path=str(base / f"{name}.db"),
                    workdir=str(base / "work"),
                    kill_switch=str(base / f"{name}.kill"),
                )
                a = build_remote_adapter(
                    config, hub_client=hub, pr_client=pr, clock=lambda: clock[0]
                )
                if executor is not None:
                    a.executor = executor
                return a

            def results(pr, kind="RESULT"):
                return [c for c in pr.items if f"[OC-COORD-INPUT] {kind}:" in c["body"]]

            def agent_events(task_id):
                counts = {}
                for row in store.events():
                    parts = row["id"].split(".")
                    if row["principal"] == "agent:claude" and task_id in parts:
                        counts[parts[2]] = counts.get(parts[2], 0) + 1
                return counts

            # 1. happy path through signed ingress + hub reports + PR publisher
            pr = _FakeComments(pr_reporter)
            assign("acc-happy")
            report = adapter("happy", pr).run_once()
            bridge.cycle()
            task = store.task("acc-happy")
            scenarios.append(
                {
                    "name": "assignment_to_reconciled_result",
                    "passed": report["delivered"] == ["acc-happy"]
                    and task["state"] == "delivered"
                    and len(results(pr)) == 1
                    and len(results(pr, "RECEIPT")) == 1
                    and any('"state":"delivered"' in c["body"] for c in hub.items)
                    and {"claim", "hb", "resp"} <= set(agent_events("acc-happy")),
                    "evidence": {
                        "coordinator_state": task["state"],
                        "attempts": task["attempts"],
                        "result_comments": len(results(pr)),
                        "agent_events_via_signed_ingress": agent_events("acc-happy"),
                    },
                }
            )

            # 2. restart with a still-valid lease
            pr = _FakeComments(pr_reporter)
            assign("acc-restart")

            def crash(spec, n):
                raise RuntimeError("process killed")

            crashed = False
            try:
                adapter("restart", pr, MockClaudeExecutor(on_step=crash)).run_once()
            except RuntimeError:
                crashed = True
            resumed = adapter("restart", pr).run_once()
            task = store.task("acc-restart")
            scenarios.append(
                {
                    "name": "restart_resumes_valid_lease",
                    "passed": crashed
                    and resumed["delivered"] == ["acc-restart"]
                    and task["attempts"] == 1,
                    "evidence": {
                        "coordinator_state": task["state"],
                        "attempts": task["attempts"],
                    },
                }
            )

            # 3. cancellation via kill switch
            pr = _FakeComments(pr_reporter)
            assign("acc-cancel")
            kill = base / "cancel.kill"
            ex = MockClaudeExecutor(
                steps=5, on_step=lambda spec, n: kill.touch() if n == 2 else None
            )
            report = adapter("cancel", pr, ex).run_once()
            task = store.task("acc-cancel")
            scenarios.append(
                {
                    "name": "kill_switch_cancels",
                    "passed": report["blocked"] == ["acc-cancel"]
                    and task["state"] == "blocked",
                    "evidence": {"coordinator_state": task["state"]},
                }
            )

            # 4. ambiguous result POST reconciled without a duplicate
            pr = _FakeComments(pr_reporter)
            pr.fail_after_post = True
            assign("acc-ambiguous")
            a = adapter("ambiguous", pr)
            a.run_once()
            clock[0] += 60
            a.publisher.flush()
            scenarios.append(
                {
                    "name": "ambiguous_post_reconciled",
                    "passed": len(results(pr, "RECEIPT")) == 1
                    and len(results(pr)) == 1
                    and {o["state"] for o in a.state.outbox()} == {"sent"},
                    "evidence": {
                        "receipts": len(results(pr, "RECEIPT")),
                        "results": len(results(pr)),
                    },
                }
            )
        finally:
            server.shutdown()
            server.server_close()
    return {
        "schema": "oc.acs-claude-acceptance.v1",
        "mode": "offline",
        "label": OFFLINE_LABEL,
        "passed": all(s["passed"] for s in scenarios),
        "scenarios": scenarios,
        "transport": "real signed HTTP to a loopback coordinator (127.0.0.1); GitHub is an in-memory fake",
        "external_network_calls": 0,
        "model_calls": 0,
    }


def staging_acceptance(
    env, *, live: bool = False, opener=None, hub_client=None, pr_client=None
) -> dict:
    """One adapter cycle against staging with the mock executor; refuses anything else.

    It never creates an assignment: an owner must post a staging test
    assignment through the coordinator first. Without one the cycle claims
    nothing and the result says so.
    """
    out = {
        "schema": "oc.acs-claude-acceptance.v1",
        "mode": "staging",
        "label": STAGING_LABEL,
    }
    if live:
        return out | {
            "status": "REFUSED",
            "reason": "LIVE_EXECUTOR_REFUSED_IN_ACCEPTANCE",
        }
    config, missing, errors = RemoteConfig.from_env(env, allow_loopback=False)
    if config is None:
        return out | {
            "status": "BLOCKED",
            "missing_settings": missing,
            "config_errors": errors,
            "settings": redacted_settings(env),
        }
    readiness = readiness_report(
        env, probe=True, opener=opener, hub_client=hub_client, pr_client=pr_client
    )
    if (
        readiness["sections"]["deployment_endpoint"]["status"] != "verified"
        or readiness["sections"]["agent_ingress"]["status"] != "verified"
    ):
        return out | {
            "status": "BLOCKED",
            "reason": "STAGING_ENDPOINT_OR_AGENT_KEY_NOT_VERIFIED",
            "readiness": readiness,
        }
    adapter = build_remote_adapter(
        config, hub_client=hub_client, pr_client=pr_client, opener=opener
    )
    report = adapter.run_once()
    return out | {
        "status": "RAN",
        "cycle": report,
        "readiness": readiness,
        "note": "Mock executor only; a delivered task here proves the coordination path, not Claude.",
    }


def main(argv=None) -> int:
    import argparse
    import os

    parser = argparse.ArgumentParser(
        prog="python -m coordination.claude_staging",
        description="Claude adapter staging preflight and acceptance",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("readiness")
    r.add_argument(
        "--probe",
        action="store_true",
        help="Read-only network probes of the configured staging target",
    )
    a = sub.add_parser("accept")
    a.add_argument("--mode", choices=("offline", "staging"), required=True)
    a.add_argument(
        "--live",
        action="store_true",
        help="Refused: acceptance never runs a live executor",
    )
    args = parser.parse_args(argv)
    if args.command == "readiness":
        print(
            json.dumps(
                readiness_report(os.environ, probe=args.probe), indent=2, sort_keys=True
            )
        )
        return 0
    if args.mode == "offline":
        result = offline_acceptance()
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["passed"] else 1
    result = staging_acceptance(os.environ, live=args.live)
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0 if result["status"] == "RAN" else 2


if __name__ == "__main__":
    raise SystemExit(main())
