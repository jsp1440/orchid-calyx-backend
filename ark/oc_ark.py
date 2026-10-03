#!/usr/bin/env python3
"""OC-ARK: provider-neutral preservation and recovery runner.

This service deliberately avoids any dependency on an AI provider. It uses
ordinary Git, PostgreSQL tooling, the Azure CLI (optional), checksums, and the
local filesystem so Orchid Continuum recovery remains possible even when the
normal application stack is unavailable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

UTC = timezone.utc


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def run(cmd: list[str], *, env: dict[str, str] | None = None) -> None:
    subprocess.run(cmd, check=True, env=env)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def ensure_command(name: str) -> None:
    if shutil.which(name) is None:
        raise RuntimeError(f"Required command not found: {name}")


@dataclass
class Artifact:
    kind: str
    source: str
    path: str
    sha256: str | None = None
    bytes: int | None = None


class Ark:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.root = Path(os.environ.get("ARK_LOCAL_ROOT", config.get("local_root", "./ark-data"))).expanduser()
        self.run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        self.run_dir = self.root / "runs" / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.artifacts: list[Artifact] = []

    def inventory(self) -> dict[str, Any]:
        return {
            "generated_at": now_iso(),
            "repositories": self.config.get("repositories", []),
            "database_configured": bool(os.environ.get("DATABASE_URL")),
            "azure_configured": bool(os.environ.get("AZURE_STORAGE_ACCOUNT")) and bool(os.environ.get("AZURE_STORAGE_CONTAINER")),
            "offline_target_configured": bool(os.environ.get("ARK_OFFLINE_ROOT")),
            "required_commands": {
                name: shutil.which(name) is not None
                for name in ["git", "pg_dump", "pg_restore", "az"]
            },
        }

    def backup_repositories(self) -> None:
        ensure_command("git")
        repos_dir = self.run_dir / "git"
        repos_dir.mkdir(parents=True, exist_ok=True)
        token = os.environ.get("GITHUB_TOKEN")
        for repo in self.config.get("repositories", []):
            name = repo["name"]
            url = repo["url"]
            if token and url.startswith("https://github.com/"):
                url = url.replace("https://", f"https://x-access-token:{token}@", 1)
            target = repos_dir / f"{name}.git"
            run(["git", "clone", "--mirror", url, str(target)])
            bundle = repos_dir / f"{name}.bundle"
            run(["git", "-C", str(target), "bundle", "create", str(bundle), "--all"])
            self.artifacts.append(Artifact("git-bundle", repo["url"], str(bundle), sha256(bundle), bundle.stat().st_size))

    def backup_database(self) -> None:
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            return
        ensure_command("pg_dump")
        db_dir = self.run_dir / "database"
        db_dir.mkdir(parents=True, exist_ok=True)
        target = db_dir / "orchid-continuum.dump"
        run(["pg_dump", "--format=custom", "--no-owner", "--no-acl", "--file", str(target), database_url])
        self.artifacts.append(Artifact("postgres-custom-dump", "DATABASE_URL", str(target), sha256(target), target.stat().st_size))

    def write_manifest(self) -> Path:
        manifest = self.run_dir / "manifest.json"
        payload = {
            "ark_version": 1,
            "run_id": self.run_id,
            "created_at": now_iso(),
            "artifacts": [a.__dict__ for a in self.artifacts],
            "inventory": self.inventory(),
        }
        manifest.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return manifest

    def verify(self) -> None:
        manifest = self.run_dir / "manifest.json"
        if not manifest.exists():
            raise RuntimeError("manifest.json does not exist for this run")
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        for item in payload.get("artifacts", []):
            path = Path(item["path"])
            if not path.exists():
                raise RuntimeError(f"Missing artifact: {path}")
            expected = item.get("sha256")
            if expected and sha256(path) != expected:
                raise RuntimeError(f"Checksum mismatch: {path}")

    def copy_to_offline_target(self) -> None:
        root = os.environ.get("ARK_OFFLINE_ROOT")
        if not root:
            return
        target_root = Path(root).expanduser() / "orchid-continuum-ark" / self.run_id
        target_root.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(self.run_dir, target_root)

    def upload_to_azure(self) -> None:
        account = os.environ.get("AZURE_STORAGE_ACCOUNT")
        container = os.environ.get("AZURE_STORAGE_CONTAINER")
        if not account or not container:
            return
        ensure_command("az")
        run([
            "az", "storage", "blob", "upload-batch",
            "--account-name", account,
            "--destination", container,
            "--destination-path", self.run_id,
            "--source", str(self.run_dir),
            "--auth-mode", "login",
            "--overwrite", "false",
        ])

    def smoke_restore_git(self) -> None:
        bundles = list((self.run_dir / "git").glob("*.bundle")) if (self.run_dir / "git").exists() else []
        if not bundles:
            return
        ensure_command("git")
        with tempfile.TemporaryDirectory(prefix="oc-ark-restore-") as td:
            target = Path(td) / "restored"
            run(["git", "clone", str(bundles[0]), str(target)])
            run(["git", "-C", str(target), "fsck", "--full"])

    def backup(self) -> None:
        self.backup_repositories()
        self.backup_database()
        self.write_manifest()
        self.verify()
        self.smoke_restore_git()
        self.upload_to_azure()
        self.copy_to_offline_target()
        latest = self.root / "latest.json"
        latest.write_text(json.dumps({"run_id": self.run_id, "completed_at": now_iso(), "status": "healthy"}, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Orchid Continuum Autonomous Recovery Kit")
    parser.add_argument("command", choices=["inventory", "backup"])
    parser.add_argument("--config", default="ark/ark_config.json")
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        fallback = Path("ark/ark_config.example.json")
        if fallback.exists():
            config_path = fallback
        else:
            raise RuntimeError(f"Config not found: {args.config}")

    ark = Ark(load_config(config_path))
    if args.command == "inventory":
        print(json.dumps(ark.inventory(), indent=2, sort_keys=True))
    else:
        ark.backup()
        print(json.dumps({"run_id": ark.run_id, "status": "healthy", "run_dir": str(ark.run_dir)}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"OC-ARK failure: {exc}", file=sys.stderr)
        raise
