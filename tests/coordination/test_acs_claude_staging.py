"""Offline tests for ACS-STAGING-PREFLIGHT-002 (no external network, no model, no provider).

Network probes are exercised with fake openers or the real coordinator on
127.0.0.1; nothing here contacts GitHub, Render or Anthropic.
"""

import contextlib
import io
import json
import os
import secrets
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from coordination import claude_staging as cs
from coordination.claude_adapter import (
    ADAPTER_MARKER,
    MockClaudeExecutor,
    SignedIngressTransport,
    result_body,
)
from coordination.ingress import make_server
from coordination.store import Store

SECRET = "s" * 40
HUB_TOKEN = "hub-token-value-should-never-print"
PR_TOKEN = "pr-token-value-should-never-print"
STAGING_URL = "https://orchid-agent-coordinator-staging.onrender.com/events"


def full_env(tmp, **overrides):
    env = {
        "ACS_CLAUDE_STAGE": "staging",
        "ACS_CLAUDE_INGRESS_URL": STAGING_URL,
        "ACS_CLAUDE_KEY_ID": "claude-staging",
        "ACS_CLAUDE_KEY_SECRET": SECRET,
        "ACS_CLAUDE_HUB_TOKEN": HUB_TOKEN,
        "ACS_HUB_REPORTER_IDS": "[99]",
        "ACS_CLAUDE_PR_TOKEN": PR_TOKEN,
        "ACS_CLAUDE_PR_REPORTER_ID": "77",
        "ACS_CLAUDE_STATE_PATH": str(Path(tmp) / "adapter.db"),
        "ACS_CLAUDE_WORKDIR": str(Path(tmp) / "work"),
        "ACS_CLAUDE_KILL_SWITCH": str(Path(tmp) / "kill"),
    }
    env.update(overrides)
    return env


class Response:
    def __init__(self, status, body):
        self.status, self.body = status, body

    def read(self, n=-1):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    """Maps (method, path) to (status, json body); records requests."""

    def __init__(self, routes):
        self.routes, self.requests = routes, []

    def open(self, req, timeout=None):
        path = req.full_url.split("://", 1)[1].split("/", 1)[1]
        self.requests.append((req.get_method(), "/" + path, req))
        status, body = self.routes.get((req.get_method(), "/" + path), (None, None))
        if status is None:
            raise urllib.error.URLError("unreachable")
        payload = json.dumps(body).encode()
        if status >= 400:
            raise urllib.error.HTTPError(
                req.full_url, status, "x", {}, io.BytesIO(payload)
            )
        return Response(status, payload)


class Comments:
    def __init__(self, items=(), fail=False):
        self.items, self.fail = list(items), fail

    def comments(self):
        if self.fail:
            raise OSError("unreachable")
        return list(self.items)

    def post(self, body):
        raise AssertionError("readiness must never post")


def healthy_staging(ingress=(400, {"error": "EVENT_REFUSED"})):
    return FakeOpener(
        {
            ("GET", "/healthz"): (
                200,
                {"status": "alive", "stage": "staging", "ready": True},
            ),
            ("POST", "/events"): ingress,
        }
    )


def adapter_comment(marker, payload, user=77):
    return {
        "id": 1,
        "user": {"id": user},
        "body": result_body(marker, payload),
        "html_url": "https://github.com/jsp1440/orchid-calyx-backend/pull/1836#issuecomment-1",
    }


class TargetGuardTest(unittest.TestCase):
    def test_production_hosts_refused(self):
        for url in (
            "https://orchid-calyx-backend.onrender.com/events",
            "https://orchid-continuum-frontend-vof6.onrender.com/events",
            "https://orchid-continuum-public-api.onrender.com/events",
            "https://id.orchidcontinuum.org/events",
            "https://staging.orchidcontinuum.org/events",
            "https://orchidcontinuum.org/events",
            "https://ORCHID-CALYX-BACKEND.onrender.com/events",
        ):
            with self.assertRaisesRegex(cs.StagingConfigError, "PRODUCTION"):
                cs.check_target(url, allow_loopback=True)

    def test_only_identified_staging_https_targets(self):
        self.assertEqual(
            cs.check_target(STAGING_URL, allow_loopback=False),
            "orchid-agent-coordinator-staging.onrender.com",
        )
        for url, code in (
            ("https://example.onrender.com/events", "NOT_PINNED_STAGING_HOST"),
            ("https://a.staging.example.com/events", "NOT_PINNED_STAGING_HOST"),
            ("https://staging.attacker.example/events", "NOT_PINNED_STAGING_HOST"),
            (
                "https://orchid-agent-coordinator-staging.onrender.com.attacker.example/events",
                "NOT_PINNED_STAGING_HOST",
            ),
            (
                "https://orchid-agent-coordinator-staging-x.onrender.com/events",
                "NOT_PINNED_STAGING_HOST",
            ),
            (
                "https://orchid-agent-coordinator-staging.onrender.com:8443/events",
                "NOT_PINNED_STAGING_HOST",
            ),
            ("http://x-staging.example.com/events", "HTTPS"),
            ("https://x-staging.example.com/other", "BARE_EVENTS_PATH"),
            ("https://x-staging.example.com/events?a=1", "BARE_EVENTS_PATH"),
            ("https://u:p@x-staging.example.com/events", "BARE_EVENTS_PATH"),
            ("http://127.0.0.1:8765/events", "LOOPBACK_NOT_A_STAGING_TARGET"),
            ("", "BARE_EVENTS_PATH"),
        ):
            with self.assertRaisesRegex(cs.StagingConfigError, code):
                cs.check_target(url, allow_loopback=False)
        self.assertEqual(
            cs.check_target("http://127.0.0.1:8765/events", allow_loopback=True),
            "127.0.0.1",
        )


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_missing_settings_fail_closed_with_names_only(self):
        config, missing, errors = cs.RemoteConfig.from_env({})
        self.assertIsNone(config)
        self.assertEqual(missing, [s.name for s in cs.SETTINGS])
        self.assertEqual(errors, [])
        env = full_env(self.tmp)
        del env["ACS_CLAUDE_PR_TOKEN"]
        config, missing, _ = cs.RemoteConfig.from_env(env)
        self.assertIsNone(config)
        self.assertEqual(missing, ["ACS_CLAUDE_PR_TOKEN"])

    def test_invalid_values_refused(self):
        env = full_env(
            self.tmp,
            ACS_CLAUDE_STAGE="production",
            ACS_CLAUDE_INGRESS_URL="https://orchid-calyx-backend.onrender.com/events",
            ACS_CLAUDE_KEY_SECRET="short",
            ACS_HUB_REPORTER_IDS='[99, "x"]',
            ACS_CLAUDE_PR_REPORTER_ID="-1",
        )
        config, missing, errors = cs.RemoteConfig.from_env(env)
        self.assertIsNone(config)
        self.assertEqual(missing, [])
        self.assertEqual(
            set(errors),
            {
                "STAGE_NOT_STAGING",
                "PRODUCTION_TARGET_REFUSED",
                "AGENT_KEY_TOO_SHORT",
                "HUB_REPORTER_IDS_INVALID",
                "PR_REPORTER_ID_INVALID",
            },
        )

    def test_credential_reuse_across_roles_refused(self):
        for overrides in (
            {"ACS_CLAUDE_PR_TOKEN": SECRET},
            {"ACS_CLAUDE_HUB_TOKEN": SECRET},
            {"ACS_CLAUDE_HUB_TOKEN": PR_TOKEN},
        ):
            config, _, errors = cs.RemoteConfig.from_env(
                full_env(self.tmp, **overrides)
            )
            self.assertIsNone(config, overrides)
            self.assertIn("CREDENTIAL_REUSED_ACROSS_ROLES", errors)

    def test_malformed_ingress_urls_refused_structurally_without_traffic(self):
        for url in (
            "https://[invalid/events",
            "https://orchid-agent-coordinator-staging.onrender.com:not-a-port/events",
            "https://orchid-agent-coordinator-staging.onrender.com:70000/events",
        ):
            with self.assertRaisesRegex(cs.StagingConfigError, "INGRESS_URL_MALFORMED"):
                cs.check_target(url, allow_loopback=True)
            env = full_env(self.tmp, ACS_CLAUDE_INGRESS_URL=url)
            config, missing, errors = cs.RemoteConfig.from_env(env)
            self.assertIsNone(config)
            self.assertEqual((missing, errors), ([], ["INGRESS_URL_MALFORMED"]))
            opener = healthy_staging()
            report = cs.readiness_report(env, probe=True, opener=opener)
            self.assertFalse(report["probed"])
            self.assertEqual(report["config_errors"], ["INGRESS_URL_MALFORMED"])
            staged = cs.staging_acceptance(env, opener=opener)
            self.assertEqual(staged["status"], "BLOCKED")
            self.assertEqual(staged["config_errors"], ["INGRESS_URL_MALFORMED"])
            self.assertEqual(opener.requests, [])
            text = json.dumps(report) + json.dumps(staged)
            for value in (
                url,
                "not-a-port",
                "70000",
                "[invalid",
                SECRET,
                HUB_TOKEN,
                PR_TOKEN,
            ):
                self.assertNotIn(value, text)

    def test_attacker_staging_like_host_never_receives_traffic(self):
        opener = healthy_staging()
        env = full_env(
            self.tmp, ACS_CLAUDE_INGRESS_URL="https://staging.attacker.example/events"
        )
        report = cs.readiness_report(env, probe=True, opener=opener)
        self.assertIn("TARGET_NOT_PINNED_STAGING_HOST", report["config_errors"])
        self.assertFalse(report["probed"])
        self.assertEqual(cs.staging_acceptance(env, opener=opener)["status"], "BLOCKED")
        self.assertEqual(opener.requests, [])

    def test_valid_config_and_remote_wiring_keeps_mock_executor(self):
        config, missing, errors = cs.RemoteConfig.from_env(full_env(self.tmp))
        self.assertEqual((missing, errors), ([], []))
        self.assertEqual(
            config.result_ref,
            "https://github.com/jsp1440/orchid-calyx-backend/pull/1836",
        )
        adapter = cs.build_remote_adapter(
            config, hub_client=Comments(), pr_client=Comments()
        )
        self.assertIsInstance(adapter.transport, SignedIngressTransport)
        self.assertIsInstance(adapter.executor, MockClaudeExecutor)
        self.assertFalse(adapter.policy.live_enabled)
        self.assertEqual(adapter.policy.max_concurrent, 1)
        self.assertEqual(adapter.kill_switch, Path(self.tmp) / "kill")

    def test_secrets_never_rendered(self):
        env = full_env(self.tmp)
        text = json.dumps(cs.redacted_settings(env)) + json.dumps(
            cs.readiness_report(env)
        )
        for value in (SECRET, HUB_TOKEN, PR_TOKEN):
            self.assertNotIn(value, text)
        self.assertEqual(
            cs.redacted_settings(env)["ACS_CLAUDE_INGRESS_URL"]["host"],
            "orchid-agent-coordinator-staging.onrender.com",
        )


class ReadinessTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.env = full_env(self.tmp)

    def test_configuration_alone_is_never_ready(self):
        report = cs.readiness_report(self.env)
        self.assertFalse(report["ready"])
        self.assertFalse(report["probed"])
        s = report["sections"]
        self.assertEqual(s["deployment_endpoint"]["status"], "configured_unverified")
        self.assertEqual(s["agent_ingress"]["status"], "configured_unverified")
        self.assertEqual(
            s["reporter_authentication"]["pr_write"]["status"],
            "configured_unverified",
        )
        self.assertEqual(s["executor"]["live_runner"], "not_supported")
        self.assertEqual(s["receipt_result_evidence"]["status"], "absent")

    def test_no_probe_makes_no_request(self):
        opener = healthy_staging()
        cs.readiness_report(self.env, opener=opener)
        self.assertEqual(opener.requests, [])

    def test_probes_verify_items_separately_and_never_overall(self):
        opener = healthy_staging()
        mock_result = adapter_comment(
            "result-1",
            {"type": "RESULT", "task_id": "t", "executor": "mock-claude-offline"},
        )
        report = cs.readiness_report(
            self.env,
            probe=True,
            opener=opener,
            hub_client=Comments(),
            pr_client=Comments([mock_result]),
        )
        s = report["sections"]
        self.assertTrue(report["probed"])
        self.assertEqual(s["deployment_endpoint"]["status"], "verified")
        self.assertEqual(s["agent_ingress"]["status"], "verified")
        self.assertEqual(
            s["reporter_authentication"]["hub_read"]["status"], "read_verified"
        )
        self.assertEqual(
            s["reporter_authentication"]["pr_write"]["status"],
            "verified_by_observed_comment",
        )
        # A mock-executor result is never live evidence.
        self.assertEqual(s["receipt_result_evidence"]["status"], "absent")
        self.assertEqual(
            s["persistent_storage"]["status"], "unverified_requires_restart_proof"
        )
        self.assertFalse(report["ready"])
        self.assertIn("supported_live_runner", report["unattended_gates_missing"])
        # Probe signed with the agent key, against /events only.
        method, path, req = opener.requests[1]
        self.assertEqual((method, path), ("POST", "/events"))
        self.assertEqual(req.headers["X-acs-key"], "claude-staging")
        event = json.loads(req.data)
        self.assertEqual(event["kind"], "heartbeat")

    def test_live_result_alone_does_not_make_ready(self):
        live = adapter_comment(
            "result-2",
            {"type": "RESULT", "task_id": "t", "executor": "claude-live-runner"},
        )
        report = cs.readiness_report(
            self.env,
            probe=True,
            opener=healthy_staging(),
            hub_client=Comments(),
            pr_client=Comments([live]),
        )
        self.assertEqual(
            report["sections"]["receipt_result_evidence"]["status"], "verified"
        )
        self.assertFalse(report["ready"])

    def test_forged_or_foreign_live_results_ignored(self):
        payload = {"type": "RESULT", "task_id": "t", "executor": "claude-live-runner"}
        stranger = adapter_comment("r", payload, user=5)
        tampered = adapter_comment("r", payload)
        tampered["body"] = tampered["body"].replace('"task_id":"t"', '"task_id": "t"')
        report = cs.readiness_report(
            self.env,
            probe=True,
            opener=healthy_staging(),
            hub_client=Comments(),
            pr_client=Comments([stranger, tampered]),
        )
        self.assertEqual(
            report["sections"]["receipt_result_evidence"]["status"], "absent"
        )

    def test_failed_probes_reported_per_item(self):
        opener = FakeOpener(
            {
                ("GET", "/healthz"): (200, {"status": "alive", "stage": "production"}),
                ("POST", "/events"): (403, {"error": "AUTHORITY_OR_LEASE_REFUSED"}),
            }
        )
        report = cs.readiness_report(
            self.env,
            probe=True,
            opener=opener,
            hub_client=Comments(fail=True),
            pr_client=Comments(),
        )
        s = report["sections"]
        self.assertEqual(s["deployment_endpoint"]["status"], "failed")
        self.assertEqual(s["agent_ingress"]["status"], "failed")
        self.assertEqual(s["agent_ingress"]["http_status"], 403)
        self.assertEqual(s["reporter_authentication"]["hub_read"]["status"], "failed")
        self.assertEqual(
            s["reporter_authentication"]["pr_write"]["status"],
            "read_verified_write_unverified",
        )

    def test_any_400_is_not_enough(self):
        report = cs.readiness_report(
            self.env,
            probe=True,
            opener=healthy_staging(ingress=(400, {"error": "CONTENT_LENGTH_INVALID"})),
            hub_client=Comments(),
            pr_client=Comments(),
        )
        self.assertEqual(report["sections"]["agent_ingress"]["status"], "failed")


class IngressProbeAgainstCoordinatorTest(unittest.TestCase):
    """The probe against the real coordinator: authenticates, writes nothing."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = Store(str(Path(self.tmp) / "acs.db"))
        self.store.initialize()
        self.agent_secret = secrets.token_hex(32)
        self.owner_secret = secrets.token_hex(32)
        keys = {
            "claude-k": {
                "secret": self.agent_secret,
                "role": "agent",
                "name": "claude",
            },
            "owner-k": {"secret": self.owner_secret, "role": "owner", "name": "owner"},
        }
        self.server = make_server(self.store, keys, port=0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/events"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def probe(self, key_id, secret):
        env = full_env(
            self.tmp,
            ACS_CLAUDE_INGRESS_URL=self.url,
            ACS_CLAUDE_KEY_ID=key_id,
            ACS_CLAUDE_KEY_SECRET=secret,
        )
        config, _, errors = cs.RemoteConfig.from_env(env, allow_loopback=True)
        self.assertEqual(errors, [])
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        return cs._probe_ingress(opener, config)

    def test_agent_key_verified_without_any_write(self):
        result = self.probe("claude-k", self.agent_secret)
        self.assertEqual(result["status"], "verified")
        self.assertEqual(self.store.events(), [])

    def test_owner_wrong_or_unknown_key_rejected(self):
        self.assertEqual(self.probe("owner-k", self.owner_secret)["http_status"], 403)
        self.assertEqual(self.probe("claude-k", "x" * 64)["http_status"], 403)
        self.assertEqual(self.probe("nobody", self.agent_secret)["status"], "failed")
        self.assertEqual(self.store.events(), [])


class PullRequestCommentsTest(unittest.TestCase):
    def test_pinned_to_one_pr(self):
        client = cs.PullRequestComments("t", opener=FakeOpener({}))
        for path in (
            "/repos/jsp1440/orchid-calyx-backend/issues/1823/comments",
            "/repos/jsp1440/orchid-calyx-backend/issues/18360/comments",
            "/repos/other/repo/issues/1836/comments",
            "/repos/jsp1440/orchid-calyx-backend/pulls/1836/merge",
        ):
            with self.assertRaisesRegex(PermissionError, "GITHUB_PATH_REFUSED"):
                client.request("PUT", path)
        with self.assertRaises(ValueError):
            cs.PullRequestComments("")

    def test_paginates_and_posts_to_pinned_path(self):
        base = "/repos/jsp1440/orchid-calyx-backend/issues/1836/comments"
        page1 = [{"id": i} for i in range(100)]
        opener = FakeOpener(
            {
                ("GET", base + "?per_page=100&page=1"): (200, page1),
                ("GET", base + "?per_page=100&page=2"): (200, [{"id": 100}]),
                ("POST", base): (201, {"id": 7}),
            }
        )
        client = cs.PullRequestComments("tok", opener=opener)
        self.assertEqual(len(client.comments()), 101)
        self.assertEqual(client.post("hi"), {"id": 7})
        req = opener.requests[-1][2]
        self.assertEqual(req.headers["Authorization"], "Bearer tok")
        self.assertEqual(json.loads(req.data), {"body": "hi"})

    def test_oversized_response_refused(self):
        class Big(FakeOpener):
            def open(self, req, timeout=None):
                return Response(200, b"[" + b" " * (4 * 1024 * 1024 + 1) + b"]")

        with self.assertRaisesRegex(ValueError, "TOO_LARGE"):
            cs.PullRequestComments("t", opener=Big({})).comments()

    def test_hub_reader_never_posts(self):
        reader = cs.HubReader("t", {99}, client=Comments([{"id": 1}]))
        self.assertEqual(reader.comments(), [{"id": 1}])
        with self.assertRaises(PermissionError):
            reader.post("x")


class AcceptanceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_offline_acceptance_is_labelled_local_mock_proof(self):
        result = cs.offline_acceptance()
        self.assertTrue(result["passed"], result)
        self.assertTrue(result["label"].startswith("LOCAL_MOCK_PROOF"))
        self.assertEqual(result["external_network_calls"], 0)
        self.assertEqual(result["model_calls"], 0)
        self.assertEqual(
            [s["name"] for s in result["scenarios"]],
            [
                "assignment_to_reconciled_result",
                "restart_resumes_valid_lease",
                "kill_switch_cancels",
                "ambiguous_post_reconciled",
            ],
        )
        happy = result["scenarios"][0]["evidence"]["agent_events_via_signed_ingress"]
        self.assertEqual(happy["claim"], 1)
        self.assertGreaterEqual(happy["hb"], 1)
        self.assertEqual(happy["resp"], 1)

    def test_staging_refuses_live(self):
        result = cs.staging_acceptance(full_env(self.tmp), live=True)
        self.assertEqual(result["status"], "REFUSED")

    def test_staging_blocked_without_config_and_makes_no_request(self):
        opener = healthy_staging()
        result = cs.staging_acceptance({}, opener=opener)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("ACS_CLAUDE_KEY_SECRET", result["missing_settings"])
        self.assertEqual(opener.requests, [])

    def test_staging_refuses_production_and_loopback_targets(self):
        for url in (
            "https://orchid-calyx-backend.onrender.com/events",
            "http://127.0.0.1:8765/events",
        ):
            opener = healthy_staging()
            result = cs.staging_acceptance(
                full_env(self.tmp, ACS_CLAUDE_INGRESS_URL=url), opener=opener
            )
            self.assertEqual(result["status"], "BLOCKED")
            self.assertTrue(result["config_errors"])
            self.assertEqual(opener.requests, [])

    def test_staging_blocked_when_probes_fail(self):
        opener = healthy_staging(ingress=(403, {"error": "AUTHORITY_OR_LEASE_REFUSED"}))
        result = cs.staging_acceptance(
            full_env(self.tmp),
            opener=opener,
            hub_client=Comments(),
            pr_client=Comments(),
        )
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["reason"], "STAGING_ENDPOINT_OR_AGENT_KEY_NOT_VERIFIED")

    def test_staging_cycle_with_mock_executor_and_nothing_assigned(self):
        opener = healthy_staging()
        result = cs.staging_acceptance(
            full_env(self.tmp),
            opener=opener,
            hub_client=Comments(),
            pr_client=Comments(),
        )
        self.assertEqual(result["status"], "RAN")
        self.assertTrue(result["label"].startswith("STAGING_COORDINATION_PATH"))
        self.assertEqual(result["cycle"]["delivered"], [])

    def test_cli(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(cs.main(["readiness"]), 0)
            self.assertFalse(json.loads(out.getvalue())["ready"])
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(cs.main(["accept", "--mode", "staging"]), 2)
            self.assertEqual(json.loads(out.getvalue())["status"], "BLOCKED")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(cs.main(["accept", "--mode", "staging", "--live"]), 2)
            self.assertEqual(json.loads(out.getvalue())["status"], "REFUSED")


class MarkerTest(unittest.TestCase):
    def test_adapter_marker_shared_with_reviewed_adapter(self):
        self.assertTrue(
            result_body("m", {"type": "RESULT", "task_id": "t"}).startswith(
                f"<!-- {ADAPTER_MARKER}:m -->"
            )
        )


if __name__ == "__main__":
    unittest.main()
