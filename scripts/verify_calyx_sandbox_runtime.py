from __future__ import annotations

import os
import socket
from pathlib import Path


def _must_fail_write(path: Path) -> None:
    try:
        path.write_text("forbidden", encoding="utf-8")
    except OSError:
        return
    raise AssertionError(f"write unexpectedly succeeded: {path}")


def main() -> None:
    workspace = Path(os.environ.get("CALYX_SANDBOX_WORKSPACE", "/workspace")).resolve()
    assert workspace.is_dir(), "sandbox workspace missing"
    assert os.environ.get("CALYX_SANDBOX_EXPECT_NETWORK_DISABLED") == "1"
    assert os.environ.get("CALYX_SANDBOX_EXPECT_REPOSITORY_READ_ONLY") == "1"
    assert os.environ.get("CALYX_SANDBOX_EXPECT_CREDENTIALS_ABSENT") == "1"

    for key in (
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AZURE_CLIENT_SECRET",
        "DATABASE_URL",
    ):
        assert not os.environ.get(key), f"credential leaked into sandbox: {key}"

    status = Path("/proc/self/status").read_text(encoding="utf-8")
    assert "NoNewPrivs:\t1" in status, "no-new-privileges not enforced"

    _must_fail_write(workspace / ".calyx-sandbox-write-probe")
    _must_fail_write(Path("/calyx-root-write-probe"))

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1.0)
    try:
        result = sock.connect_ex(("1.1.1.1", 443))
    finally:
        sock.close()
    assert result != 0, "network connection unexpectedly succeeded"

    print("CALYX_SANDBOX_RUNTIME_VERIFIED")


if __name__ == "__main__":
    main()
