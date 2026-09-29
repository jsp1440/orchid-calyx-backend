"""Run declared validation commands and record what actually happened.

This is the deterministic lane's second executor. ``reconcile`` settles an issue
from a disposition the issue itself declares; this one settles it from the exit
codes of commands that really ran, so a completed cycle carries execution
evidence rather than a restated intention.

Three rules follow from that and are enforced here rather than left to a caller:

* a declared command that does not exist is a failure, never a skip — otherwise
  a task could declare validation, run none, and settle as validated;
* a non-zero exit, a timeout, or a runner error is a failure regardless of the
  disposition the issue declared, because a task may not authorise its own pass;
* provider and GitHub credentials are removed from the child environment, so a
  command cannot spend money or mutate the repository even by accident. The lane
  promises zero provider calls; that promise is worth more as a property of the
  environment than as a sentence in a receipt.

Pure enough to test: the subprocess runner is injectable, and nothing here reads
the clock except to measure a duration it reports.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.util
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent


def _load_sibling(module_name: str, filename: str):
    """Import a sibling script, whichever way this file was started.

    The control-plane scripts are launched both as ``python3 -m scripts.x``,
    where the package is importable, and as ``python3 scripts/x.py``, where
    ``sys.path[0]`` is ``scripts/`` and the package is not. The package import
    is tried first on purpose: loading the same file twice under two module
    names produces two copies of every class in it, and an ``except`` clause
    then fails to catch an exception that looks identical.
    """
    try:
        return importlib.import_module(f"scripts.{module_name}")
    except ImportError:
        pass
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(module_name, _HERE / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"required module unavailable: {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_COMMANDS = _load_sibling("oc_validation_commands", "oc_validation_commands.py")

UnknownValidationCommand = _COMMANDS.UnknownValidationCommand
DEFAULT_TIMEOUT_SECONDS = _COMMANDS.DEFAULT_TIMEOUT_SECONDS

EVIDENCE_SCHEMA = "oc.provider-free-validation-evidence.v1"

#: How much command output travels in the receipt. Enough to identify a failure
#: from the issue thread; not so much that a receipt becomes a log dump nobody
#: reads. The digest below covers the whole output, so the tail being short does
#: not make the evidence unverifiable.
OUTPUT_TAIL_CHARACTERS = 2000

#: Environment names removed from every child process. Prefix matches cover the
#: provider SDKs' own variants (``ANTHROPIC_AUTH_TOKEN``, ``OPENAI_ORG_ID``, …)
#: without needing to enumerate them.
_STRIPPED_PREFIXES = (
    "ANTHROPIC_",
    "OPENAI_",
    "GEMINI_",
    "GOOGLE_API",
    "AZURE_OPENAI",
    "GH_",
    "GITHUB_TOKEN",
    "OC_GOVERNOR_",
)
_STRIPPED_SUFFIXES = ("_API_KEY", "_TOKEN", "_SECRET", "_PASSWORD")


def sanitized_environment(source: dict[str, str] | None = None) -> dict[str, str]:
    """Return an environment with credentials and governor policy removed.

    Governor policy goes too. A validation command has no business reading the
    budget state, and leaving it visible invites a future command to branch on
    it — which would put spending policy inside a lane that is supposed to be
    incapable of spending.
    """
    env = dict(os.environ if source is None else source)
    for name in list(env):
        upper = name.upper()
        if upper.startswith(_STRIPPED_PREFIXES) or upper.endswith(_STRIPPED_SUFFIXES):
            del env[name]
    # Keep child output deterministic and unbuffered so a timeout still yields
    # the tail that explains it.
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def _tail(text: str) -> str:
    if len(text) <= OUTPUT_TAIL_CHARACTERS:
        return text
    return "…" + text[-OUTPUT_TAIL_CHARACTERS:]


CommandResult = dict[str, Any]
Runner = Callable[[tuple[str, ...], str | None, int], subprocess.CompletedProcess[str]]


def _default_runner(
    argv: tuple[str, ...], cwd: str | None, timeout: int
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv),
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=sanitized_environment(),
    )


def run_validation(
    command_ids: list[str],
    *,
    cwd: str | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    runner: Runner | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Run every declared command and return evidence of what each one did.

    Commands run in declared order and every one of them runs: a later command
    is not skipped because an earlier one failed, because the point of the
    receipt is to say what the revision does, and stopping at the first failure
    hides the rest of the answer. ``passed`` is true only when every command
    exited zero.
    """
    commands = _COMMANDS.resolve(command_ids)
    execute = runner or _default_runner
    results: list[CommandResult] = []

    for command in commands:
        started = clock()
        timed_out = False
        runner_error: str | None = None
        exit_code: int | None = None
        output = ""
        try:
            completed = execute(command.argv, cwd, timeout)
            exit_code = int(completed.returncode)
            output = (completed.stdout or "") + (completed.stderr or "")
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            output = _decode(exc.stdout) + _decode(exc.stderr)
        except (OSError, ValueError) as exc:
            # A runner that could not start is not a pass and not a skip. Name
            # the failure class without echoing an argument vector back through
            # an error message.
            runner_error = type(exc).__name__
        duration = round(max(0.0, clock() - started), 3)
        results.append(
            {
                "command_id": command.command_id,
                "argv": list(command.argv),
                "summary": command.summary,
                "proves": command.proves,
                "exit_code": exit_code,
                "passed": exit_code == 0 and not timed_out and runner_error is None,
                "timed_out": timed_out,
                "runner_error": runner_error,
                "duration_seconds": duration,
                "output_digest": _digest(output),
                "output_tail": _tail(output),
            }
        )

    return {
        "schema": EVIDENCE_SCHEMA,
        "passed": bool(results) and all(row["passed"] for row in results),
        "command_count": len(results),
        "failed_command_ids": [row["command_id"] for row in results if not row["passed"]],
        "results": results,
        "safety": {
            "provider_calls": False,
            "credentials_visible_to_commands": False,
            "merge_to_main": False,
            "production_deploy": False,
            "scientific_mutation": False,
        },
    }


def _decode(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--command",
        action="append",
        default=[],
        help="A validation command id; repeatable, resolved against the registry.",
    )
    parser.add_argument("--cwd", default=None)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    args = parser.parse_args(argv)

    try:
        evidence = run_validation(args.command, cwd=args.cwd, timeout=args.timeout)
    except UnknownValidationCommand as exc:
        json.dump(
            {"schema": EVIDENCE_SCHEMA, "passed": False, "error": str(exc)},
            sys.stdout,
            sort_keys=True,
        )
        sys.stdout.write("\n")
        return 2

    json.dump(evidence, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
