"""Execute the Edith Bramble source-under-test and compare its build with the live runtime.

Runs on a GitHub-hosted runner (never on a coding-agent container). Writes a
list of CertificationGate objects to --out for
``run_edith_bramble_certification.py --finalize`` to merge:

- app_build / app_lint / app_typecheck: exit code and output tail of the
  application's own commands (`npm run build`, `npm run lint`, `tsc`).
  Dependencies are installed with --ignore-scripts.
- compiled_asset_correspondence: the build of the selected archive versus
  the JavaScript the live runtime serves, by exact sha256 and by
  bidirectional prose-literal coverage.
- runtime_secret_exposure: every JWT in the deployed JavaScript is decoded
  and its role claim recorded; a non-anon role is a failure.

A command that could not run is BLOCKED, never PASS.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import re
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from urllib.parse import quote

import httpx

_CODE_LIKE = re.compile(r"[{}()<>=;|&\[\]]|\b(?:const|return|classname|function)\b")
COVERAGE_MIN = 0.99


def gate(gate_id: str, status: str, evidence: str, *, kind: str = "test",
         blocker: str | None = None, action: str | None = None) -> dict:
    return {
        "gate_id": gate_id, "status": status, "evidence_type": kind,
        "observed_evidence": evidence,
        "blocker": blocker if status != "PASS" else None,
        "smallest_next_action": action if status != "PASS" else None,
    }


def run(cmd: list[str], cwd: Path, timeout: int) -> tuple[int | None, str, float]:
    started = time.monotonic()
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False)
        out = (proc.stdout + "\n" + proc.stderr).strip()
        return proc.returncode, out, time.monotonic() - started
    except subprocess.TimeoutExpired:
        return None, f"timed out after {timeout}s", time.monotonic() - started
    except OSError as exc:
        return None, f"{type(exc).__name__}: {exc}", time.monotonic() - started


def tail(text: str, lines: int = 25) -> str:
    return " / ".join(line.strip() for line in text.splitlines()[-lines:] if line.strip())[:3000]


def prose(text: str) -> set[str]:
    found = {
        " ".join(m.split()).lower()
        for m in re.findall(r"[\"']([^\"'\\\n`]{40,400})[\"']", text)
        if not re.search(r"https?://|\.(?:png|jpe?g|svg|webp)\b", m)
    }
    return {lit for lit in found if not _CODE_LIKE.search(lit) and len(re.findall(r"[a-z]{2,}", lit)) >= 6}


def decode_escapes(text: str) -> str:
    return re.sub(r"\\u\{?([0-9a-fA-F]{4,5})\}?", lambda m: chr(int(m.group(1), 16)), text)


def deployed_scripts(client: httpx.Client, runtime: str) -> dict[str, str]:
    page = client.get(runtime)
    page.raise_for_status()
    base = httpx.URL(str(page.url))
    out: dict[str, str] = {}
    for src in re.findall(r"<script[^>]+src=[\"']([^\"']+)[\"']", page.text, re.IGNORECASE):
        url = base.join(src)
        if url.host == base.host:
            response = client.get(url)
            if response.status_code == 200:
                out[url.path.rsplit("/", 1)[-1]] = response.text
    return out


def jwt_roles(text: str) -> list[tuple[str, str]]:
    roles = []
    for token in set(re.findall(r"eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}", text)):
        payload = token.split(".")[1]
        try:
            claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        except ValueError:
            continue
        roles.append((f"{token[:12]}...{token[-6:]}", str(claims.get("role"))))
    return sorted(roles)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-repo", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--archive", required=True)
    parser.add_argument("--runtime-url", required=True)
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    gates: list[dict] = []
    client = httpx.Client(timeout=60, follow_redirects=True)
    raw = (f"https://raw.githubusercontent.com/{args.source_repo}/{args.source_sha}/"
           f"{quote(args.archive, safe='/')}")
    archive = client.get(raw)
    archive.raise_for_status()
    identity = f"{args.source_repo}@{args.source_sha}:{args.archive} sha256={hashlib.sha256(archive.content).hexdigest()}"
    app = args.workdir / "app"
    app.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(archive.content)) as zf:
        zf.extractall(app)
    # The export may be wrapped in a single top-level directory.
    if not (app / "package.json").exists():
        nested = [p.parent for p in app.glob("*/package.json")]
        if len(nested) == 1:
            app = nested[0]

    install_rc, install_out, install_s = run(
        ["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"], app, 900
    )
    installed = install_rc == 0
    if not installed:
        for gate_id in ("app_build", "app_lint", "app_typecheck"):
            gates.append(gate(
                gate_id, "BLOCKED",
                f"{identity}: `npm ci --ignore-scripts` exited {install_rc} after {install_s:.0f}s: {tail(install_out)}",
                blocker="Dependencies could not be installed, so the command was not run.",
                action="Repair the lockfile/dependency install, then re-run certification.",
            ))
    else:
        tsconfig = "tsconfig.app.json" if (app / "tsconfig.app.json").exists() else "tsconfig.json"
        for gate_id, cmd in (
            ("app_build", ["npm", "run", "build"]),
            ("app_lint", ["npm", "run", "lint"]),
            ("app_typecheck", ["npx", "--no-install", "tsc", "--noEmit", "-p", tsconfig]),
        ):
            rc, out, secs = run(cmd, app, 900)
            status = "PASS" if rc == 0 else ("BLOCKED" if rc is None else "FAIL")
            gates.append(gate(
                gate_id, status,
                f"{identity}: `{' '.join(cmd)}` exited {rc} in {secs:.0f}s; output tail: {tail(out)}",
                blocker=f"`{' '.join(cmd)}` did not succeed.",
                action=f"Fix the {gate_id.removeprefix('app_')} errors in the source-under-test, then re-run.",
            ))

    try:
        live = deployed_scripts(client, args.runtime_url)
    except httpx.HTTPError as exc:
        live = {}
        gates.append(gate("compiled_asset_correspondence", "BLOCKED",
                          f"Live runtime scripts unavailable: {type(exc).__name__}: {exc}",
                          kind="deployment", blocker="Live runtime unreachable from the runner."))
    built_ok = any(g["gate_id"] == "app_build" and g["status"] == "PASS" for g in gates)
    if live and not built_ok:
        gates.append(gate("compiled_asset_correspondence", "BLOCKED",
                          "The source-under-test did not build, so no compiled asset can be compared.",
                          kind="deployment", blocker="No build output to compare."))
    elif live:
        built = {p.name: p.read_text(encoding="utf-8", errors="replace")
                 for p in sorted((app / "dist").rglob("*.js"))}
        live_sha = {n: hashlib.sha256(t.encode()).hexdigest() for n, t in live.items()}
        built_sha = {n: hashlib.sha256(t.encode()).hexdigest() for n, t in built.items()}
        exact = sorted(set(live_sha.values()) & set(built_sha.values()))
        live_prose = prose(decode_escapes("\n".join(live.values())))
        built_prose = prose(decode_escapes("\n".join(built.values())))
        both = live_prose & built_prose
        live_cov = len(both) / len(live_prose) if live_prose else 0.0
        built_cov = len(both) / len(built_prose) if built_prose else 0.0
        only_live = sorted(live_prose - built_prose)[:3]
        only_built = sorted(built_prose - live_prose)[:3]
        verified = bool(exact) or (live_cov >= COVERAGE_MIN and built_cov >= COVERAGE_MIN)
        gates.append(gate(
            "compiled_asset_correspondence", "PASS" if verified else "FAIL",
            (f"Source-under-test {identity}. Live scripts {live_sha}; built scripts {built_sha}; "
             f"identical sha256: {exact or 'none'}. Prose literals: live {len(live_prose)}, built "
             f"{len(built_prose)}, shared {len(both)} (live covered {live_cov:.1%}, built covered "
             f"{built_cov:.1%}); live-only examples {[s[:80] for s in only_live]}; built-only "
             f"examples {[s[:80] for s in only_built]}."),
            kind="deployment",
            blocker="The build of the source-under-test is not the JavaScript the live runtime serves.",
            action="Commit the exact source of the deployed Famous build, then re-run certification.",
        ))

    if live:
        roles = jwt_roles("\n".join(live.values()))
        privileged = [r for r in roles if r[1] not in {"anon"}]
        gates.append(gate(
            "runtime_secret_exposure", "FAIL" if privileged else "PASS",
            f"JWTs in live JavaScript (redacted) with role claims: {roles or 'none'}.",
            kind="deployment",
            blocker="A non-anon credential is shipped to every browser.",
            action="Rotate the exposed credential (owner) and remove it from client code.",
        ))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(gates, indent=2) + "\n", encoding="utf-8")
    for g in gates:
        print(f"{g['gate_id']}: {g['status']} -- {g['observed_evidence'][:400]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
