"""Run only changed integration tests with a private ephemeral PostgreSQL."""
from __future__ import annotations

import argparse
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--test-selector", action="append")
    args = parser.parse_args()
    selectors = args.test_selector or [
        "tests/test_r1_claim_budget.py", "tests/test_r1_brain_producer.py",
    ]
    if any(not selector.startswith(("tests/test_r1_claim_budget.py",
                                    "tests/test_r1_brain_producer.py")) for selector in selectors):
        parser.error("only changed integration tests are permitted")
    root = Path(__file__).resolve().parents[1]
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="orchid-r1-tests-") as temp:
        home = Path(temp)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        dsn = f"postgresql://oc_local@127.0.0.1:{port}/postgres"
        pg_ctl, initdb, git, bash = (shutil.which(name) for name in
                                   ("pg_ctl", "initdb", "git", "bash"))
        if not all((pg_ctl, initdb, git, bash)):
            raise RuntimeError("LOCAL_TEST_BINARIES_REQUIRED")
        env = {
            "PATH": ":".join(sorted({str(Path(x).parent) for x in (pg_ctl, git, bash)})),
            "HOME": str(home), "TMPDIR": str(home),
            "PYTHONPATH": ":".join((str(root), *(p for p in sys.path if p.endswith("site-packages")))),
            "DATABASE_URL": dsn, "TEST_DATABASE_URL": dsn,
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONDONTWRITEBYTECODE": "1",
            "NO_API_MODE": "true", "OC_GOVERNOR_PAID_EXECUTION_ENABLED": "false",
            "PROVIDER_LAUNCH_AUTHORIZED": "false", "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
        }

        def run(argv, name):
            with (out / name).open("w") as log:
                return subprocess.run(argv, cwd=root, env=env, stdout=log,
                                      stderr=subprocess.STDOUT, timeout=180).returncode

        data = home / "postgres"
        if run([initdb, "-D", str(data), "-U", "oc_local", "-A", "trust",
                "--no-locale"], "initdb.log"):
            raise RuntimeError("ISOLATED_POSTGRES_INITIALIZATION_FAILED")
        if run([pg_ctl, "-D", str(data), "-l", str(home / "postgres.log"), "-o",
                f"-h 127.0.0.1 -p {port} -k {home}", "-w", "start"], "start.log"):
            raise RuntimeError("ISOLATED_POSTGRES_START_FAILED")
        try:
            guard = (
                "from scripts.oc_program_autonomy_timer_proof import "
                "_install_socket_guard,_guard_selftest;"
                f"_install_socket_guard('127.0.0.1:{port}',None);"
                "assert _guard_selftest(None);import pytest;raise SystemExit(pytest.main("
                f"{['-q', *selectors, '--junitxml=' + str(out / 'tests.xml')]!r}))"
            )
            code = run([sys.executable, "-c", guard], "tests.log")
        finally:
            if run([pg_ctl, "-D", str(data), "-m", "immediate", "-w", "stop"],
                   "stop.log"):
                raise RuntimeError("ISOLATED_POSTGRES_STOP_FAILED")
        raise SystemExit(code)


if __name__ == "__main__":
    main()
