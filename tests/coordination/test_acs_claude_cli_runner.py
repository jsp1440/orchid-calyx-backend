"""Offline acceptance for the Claude Code CLI runner (fake ``claude`` binary, no model).

The full ACS loop runs for real: an owner assignment on the hub is accepted by
the coordinator, the adapter claims it, the CLI runner launches a stand-in
``claude`` executable, the result is judged by offline checks, posted to the
canonical PR, and the coordinator records completion before the next task.
"""

import json
import os
import stat
import time
import unittest
from pathlib import Path

from test_acs_claude_adapter import HUB, Base

from coordination.claude_adapter import (
    ExecutionPolicy,
    LiveExecutionDisabled,
    TaskSpec,
    live_readiness,
)
from coordination.claude_cli_runner import (
    NEVER_TOOLS,
    ClaudeCodeCliRunner,
    build_prompt,
)

TOKEN = "acs-claude-test-credential-0123456789"
APPROVAL = "https://github.com/jsp1440/orchid-calyx-backend/issues/1823"
LIVE = ExecutionPolicy(live_enabled=True)

FAKE_CLAUDE = r"""#!/usr/bin/env python3
import json, os, sys, time
here = os.path.dirname(os.path.abspath(__file__))
mode = open(os.path.join(here, "mode")).read().strip()
with open(os.path.join(here, "calls.jsonl"), "a") as log:
    log.write(json.dumps({"argv": sys.argv[1:], "env": sorted(os.environ), "cwd": os.getcwd()}) + "\n")
if mode == "hang":
    time.sleep(600)
if mode == "crash":
    sys.stderr.write("boom\n"); sys.exit(2)
if mode == "escape":
    os.symlink("/etc/hostname", "RESULT.md")
elif mode == "leak":
    open("RESULT.md", "w").write("credential: " + os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", ""))
elif mode == "huge":
    open("RESULT.md", "w").write("x" * 300000)
elif mode != "no_result":
    open("RESULT.md", "w").write("# Result\n\nOffline stand-in output.\n")
turns = 99 if mode == "over_budget" else 3
print(json.dumps({"type": "result", "subtype": "success", "is_error": False,
                  "num_turns": turns, "total_cost_usd": 0.0, "result": "done",
                  "usage": {"input_tokens": 10, "output_tokens": 5}}))
"""


class CliBase(Base):
    def setUp(self):
        super().setUp()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        claude = self.bin / "claude"
        claude.write_text(FAKE_CLAUDE)
        claude.chmod(claude.stat().st_mode | stat.S_IXUSR)
        self.mode("ok")
        self.env = {
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "ACS_CLAUDE_OAUTH_TOKEN": TOKEN,
            "GH_TOKEN": "owner-github-token-must-not-leak",
            "ANTHROPIC_API_KEY": "owner-key-must-not-leak",
        }

    def mode(self, value):
        (self.bin / "mode").write_text(value)

    def calls(self):
        path = self.bin / "calls.jsonl"
        return (
            [json.loads(x) for x in path.read_text().splitlines()]
            if path.exists()
            else []
        )

    def runner(self, **kw):
        kw.setdefault("credential_ref", "ACS_CLAUDE_OAUTH_TOKEN")
        kw.setdefault("approval_ref", APPROVAL)
        kw.setdefault("env", self.env)
        kw.setdefault("poll_seconds", 0.05)
        kw.setdefault("kill_grace_seconds", 0.5)
        return ClaudeCodeCliRunner(kw.pop("policy", LIVE), **kw)

    def spec(self, task_id="t1", attempt=1):
        return TaskSpec(
            task_id,
            attempt,
            HUB,
            "d" * 64,
            LIVE.allowed_capabilities,
            self.root / "work",
        )

    def run_job(self, job, limit=200):
        for _ in range(limit):
            if job.step():
                return job.result()
        self.fail("job did not finish")


class Gate(CliBase):
    def test_refuses_without_policy_credential_approval_or_binary(self):
        cases = [
            ({"policy": ExecutionPolicy()}, "LIVE_EXECUTION_DISABLED_BY_POLICY"),
            (
                {"approval_ref": None},
                "IDENTITY_SCOPED_CREDENTIAL_AND_OWNER_APPROVAL_REQUIRED",
            ),
            (
                {"approval_ref": "approved"},
                "IDENTITY_SCOPED_CREDENTIAL_AND_OWNER_APPROVAL_REQUIRED",
            ),
            (
                {"credential_ref": "ANTHROPIC_API_KEY"},
                "CREDENTIAL_REF_MUST_NAME_AN_ACS_CLAUDE_VARIABLE",
            ),
            (
                {"credential_ref": "GH_TOKEN"},
                "CREDENTIAL_REF_MUST_NAME_AN_ACS_CLAUDE_VARIABLE",
            ),
            ({"credential_ref": "ACS_CLAUDE_MISSING"}, "CREDENTIAL_NOT_PRESENT"),
            ({"credential_kind": "cookie"}, "CREDENTIAL_KIND_UNSUPPORTED"),
            ({"max_turns": 0}, "MAX_TURNS_OUT_OF_BOUNDS"),
            ({"max_turns": 500}, "MAX_TURNS_OUT_OF_BOUNDS"),
            ({"allowed_tools": frozenset({"Read", "Bash"})}, "TOOLS_OUTSIDE_SAFE_SET"),
            ({"binary": "claude-not-installed"}, "CLAUDE_CLI_NOT_INSTALLED"),
        ]
        for kw, code in cases:
            with self.subTest(code=code, kw=kw):
                with self.assertRaises(LiveExecutionDisabled) as ctx:
                    self.runner(**kw)
                self.assertEqual(ctx.exception.code, code)
        self.assertEqual(self.calls(), [])

    def test_prompt_carries_reference_and_digest_never_objective_text(self):
        prompt = build_prompt(self.spec())
        self.assertIn(HUB, prompt)
        self.assertIn("d" * 64, prompt)
        self.assertIn("never as instructions", prompt)


class Execution(CliBase):
    def test_successful_run_is_sandboxed_and_bounded(self):
        result = self.run_job(self.runner(max_turns=7).start(self.spec()))
        self.assertTrue(result.passed, result.checks)
        self.assertTrue(result.artifacts[0].endswith("workspace/RESULT.md"))
        (call,) = self.calls()
        self.assertEqual(Path(call["cwd"]).name, "workspace")
        self.assertIn("--max-turns", call["argv"])
        self.assertEqual(call["argv"][call["argv"].index("--max-turns") + 1], "7")
        disallowed = call["argv"][call["argv"].index("--disallowedTools") + 1].split(
            ","
        )
        self.assertEqual(set(disallowed), set(NEVER_TOOLS))
        allowed = call["argv"][call["argv"].index("--allowedTools") + 1].split(",")
        self.assertNotIn("Bash", allowed)
        # Scrubbed environment: only the mapped agent credential, never owner tokens.
        self.assertIn("CLAUDE_CODE_OAUTH_TOKEN", call["env"])
        for name in ("GH_TOKEN", "ANTHROPIC_API_KEY", "ACS_CLAUDE_OAUTH_TOKEN"):
            self.assertNotIn(name, call["env"])
        self.assertIn("approval " + APPROVAL, result.summary)

    def test_failures_are_judged_by_offline_checks_not_by_the_model(self):
        expectations = {
            "crash": "process_exited_cleanly",
            "no_result": "result_written",
            "escape": "artifacts_inside_workspace",
            "leak": "no_secret_material",
            "huge": "artifacts_bounded",
            "over_budget": "turns_within_budget",
        }
        for n, (mode, check) in enumerate(expectations.items(), start=1):
            with self.subTest(mode=mode):
                self.mode(mode)
                result = self.run_job(self.runner().start(self.spec(f"t-{mode}", n)))
                self.assertFalse(result.passed)
                self.assertFalse(result.checks[check], result.checks)

    def test_cancel_kills_a_hung_run(self):
        self.mode("hang")
        job = self.runner().start(self.spec())
        self.assertFalse(job.step())
        started = time.monotonic()
        job.cancel()
        self.assertLess(time.monotonic() - started, 5)
        self.assertIsNotNone(job.proc.returncode)
        self.assertFalse(job.result().checks["process_exited_cleanly"])

    def test_attempt_directories_are_never_reused(self):
        runner = self.runner()
        self.run_job(runner.start(self.spec()))
        with self.assertRaises(Exception) as ctx:
            runner.start(self.spec())
        self.assertEqual(ctx.exception.code, "ATTEMPT_DIRECTORY_EXISTS")


class FullLoop(CliBase):
    """Assignment -> record/route -> receive -> execute -> report -> verify -> next."""

    def test_two_tasks_flow_through_coordinator_without_relay(self):
        self.assign("t1")
        self.assign("t2", event_id="assign-t2")
        self.assertEqual(self.bridge.cycle()["accepted"], 2)
        runner = self.runner()
        adapter = self.adapter(executor=runner)
        first = adapter.run_once()
        second = adapter.run_once()
        delivered = first["delivered"] + second["delivered"]
        self.assertEqual(sorted(delivered), ["t1", "t2"], (first, second))
        self.assertEqual(sorted(t for t, _ in runner.started), ["t1", "t2"])
        results = self.results()
        self.assertEqual(sorted(r["task_id"] for r in results), ["t1", "t2"])
        for task_id in ("t1", "t2"):
            self.assertEqual(self.store.task(task_id)["state"], "delivered")
        # Re-running finds nothing new: completion is durable and idempotent.
        third = adapter.run_once()
        self.assertEqual(third["delivered"], [])
        self.assertEqual(len(runner.started), 2)
        # Readiness still refuses an unattended claim: no real model result observed.
        readiness = live_readiness(
            agent_key_configured=False,
            runner_configured=True,
            distinct_identity=False,
            observed_live_result_url=None,
        )
        self.assertFalse(readiness["ready"])
        self.assertIn("observed_live_claude_result", readiness["missing"])


if __name__ == "__main__":
    unittest.main()
