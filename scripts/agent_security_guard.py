#!/usr/bin/env python3
"""Fail closed on autonomous-agent governance drift and unsafe permission modes.

This guard is intentionally static and conservative. It does not attempt to infer
private reasoning. It checks the PR diff for protected control-plane writes and
known permission/sandbox bypass settings.
"""

from __future__ import annotations

import argparse
import fnmatch
import re
import subprocess
import sys
from pathlib import Path

GUARD_PATH = "scripts/agent_security_guard.py"

PROTECTED_PATHS = (
    "AGENTS.md",
    "CLAUDE.md",
    ".github/copilot-instructions.md",
    ".agents/**",
    ".claude/**",
    ".cursor/**",
    ".vscode/**",
    ".github/workflows/agent-security-guard.yml",
    GUARD_PATH,
    "docs/AGENT-SECURITY-BOUNDARIES.md",
)

SCANNED_SUFFIXES = {
    ".json", ".jsonc", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".sh", ".bash", ".zsh", ".py", ".js", ".jsx", ".ts", ".tsx",
}

DANGEROUS_PATTERNS = (
    re.compile(r"--dangerously-skip-permissions", re.I),
    re.compile(r"\bbypassPermissions\b", re.I),
    re.compile(r"\bdangerouslyDisableSandbox\b", re.I),
    re.compile(r"\bdanger[-_ ]full[-_ ]access\b", re.I),
    re.compile(r"\binsecure[-_ ]none\b", re.I),
    re.compile(r"\bdisable(?:d)?[-_ ]sandbox\b", re.I),
    re.compile(r"\bno[-_ ]sandbox\b", re.I),
)


def git(*args: str) -> str:
    proc = subprocess.run(
        ["git", *args], check=False, text=True, capture_output=True
    )
    if proc.returncode:
        sys.stderr.write(proc.stderr)
        raise SystemExit(proc.returncode)
    return proc.stdout


def exists_at(ref: str, path: str) -> bool:
    return subprocess.run(
        ["git", "cat-file", "-e", f"{ref}:{path}"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0


def is_protected(path: str) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in PROTECTED_PATHS)


def added_lines(base: str, head: str, path: str) -> list[str]:
    diff = git("diff", "--unified=0", f"{base}..{head}", "--", path)
    lines: list[str] = []
    for line in diff.splitlines():
        if line.startswith("+++ "):
            continue
        if line.startswith("+"):
            lines.append(line[1:])
    return lines


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    args = parser.parse_args()

    changed = [
        p.strip()
        for p in git("diff", "--name-only", f"{args.base}..{args.head}").splitlines()
        if p.strip()
    ]

    bootstrap = not exists_at(args.base, GUARD_PATH)
    protected = [] if bootstrap else sorted(p for p in changed if is_protected(p))
    unsafe: list[tuple[str, str]] = []

    for path in changed:
        if path == GUARD_PATH:
            continue
        if Path(path).suffix.lower() not in SCANNED_SUFFIXES:
            continue
        for line in added_lines(args.base, args.head, path):
            for pattern in DANGEROUS_PATTERNS:
                if pattern.search(line):
                    unsafe.append((path, line.strip()[:240]))
                    break

    if bootstrap:
        print("Bootstrap mode: guard absent from base; protected-path enforcement starts after integration.")

    if protected:
        print("::error::Agent-governance/security control files changed. Owner checkpoint required before merge.")
        for path in protected:
            print(f"  - {path}")

    if unsafe:
        print("::error::Unsafe permission/sandbox bypass configuration detected in added lines.")
        for path, line in unsafe:
            print(f"  - {path}: {line}")

    if protected or unsafe:
        print("See docs/AGENT-SECURITY-BOUNDARIES.md. Do not bypass this check from agent-authored content.")
        return 1

    print(f"Agent security guard passed: {len(changed)} changed file(s), no protected-path or bypass-mode drift.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
