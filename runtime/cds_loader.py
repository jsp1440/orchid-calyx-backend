"""CDS v2 runtime registry loader.

BUILD-012B turns the Calyx Development Suite package into live API data.
The loader reads the registry/dashboard/priority files from the repository
and returns normalized dictionaries suitable for Mission Control and future
frontend dashboards.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = REPO_ROOT / "config"


class CDSRegistryError(RuntimeError):
    """Raised when CDS registry assets are missing or malformed."""


class CDSRegistryLoader:
    """Load and normalize CDS v2 operating-console data."""

    def __init__(self, config_dir: Optional[Path] = None) -> None:
        self.config_dir = config_dir or CONFIG_DIR

    def modules(self) -> list[dict[str, Any]]:
        modules = self._load_json("cds_module_registry.json")
        if not isinstance(modules, list):
            raise CDSRegistryError("cds_module_registry.json must contain a list")
        return [self._normalize_module(module) for module in modules]

    def module(self, module_id: str) -> dict[str, Any]:
        wanted = module_id.lower()
        for module in self.modules():
            if module["module_id"].lower() == wanted or module["name"].lower() == wanted:
                return module
        raise CDSRegistryError(f"CDS module not found: {module_id}")

    def priorities(self) -> list[dict[str, Any]]:
        path = self.config_dir / "cds_priorities.csv"
        if not path.exists():
            raise CDSRegistryError(f"Missing CDS priorities file: {path}")
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            priorities: list[dict[str, Any]] = []
            for row in reader:
                priorities.append(
                    {
                        "rank": int(row["rank"]),
                        "priority": row["priority"],
                    }
                )
        return priorities

    def dashboard(self) -> dict[str, Any]:
        dashboard = self._load_json("cds_dashboard.json")
        modules = self.modules()
        priorities = self.priorities()
        status_counts = Counter(module["status"] for module in modules)
        domain_counts = Counter(module["domain"] for module in modules)
        live_ready = [module for module in modules if module["status"] == "live-ready"]
        planned = [module for module in modules if module["status"] == "planned"]
        framework = [module for module in modules if module["status"] == "framework"]

        return {
            **dashboard,
            "build": "BUILD-012B",
            "source": "backend-config/cds-v2",
            "module_count": len(modules),
            "status_counts": dict(status_counts),
            "domain_counts": dict(domain_counts),
            "live_ready_modules": live_ready,
            "framework_modules": framework,
            "planned_modules": planned,
            "priorities": priorities,
        }

    def summary(self) -> dict[str, Any]:
        modules = self.modules()
        return {
            "build": "BUILD-012B",
            "suite": "Calyx Development Suite",
            "version": "v2",
            "module_count": len(modules),
            "status_counts": dict(Counter(module["status"] for module in modules)),
            "domain_counts": dict(Counter(module["domain"] for module in modules)),
            "top_priority": self.priorities()[0] if self.priorities() else None,
        }

    def _load_json(self, filename: str) -> Any:
        path = self.config_dir / filename
        if not path.exists():
            raise CDSRegistryError(f"Missing CDS registry file: {path}")
        try:
            with path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        except json.JSONDecodeError as exc:
            raise CDSRegistryError(f"Invalid JSON in {path}: {exc}") from exc

    def _normalize_module(self, module: dict[str, Any]) -> dict[str, Any]:
        required = ["module_id", "name", "domain", "purpose", "status"]
        missing = [key for key in required if not module.get(key)]
        if missing:
            raise CDSRegistryError(f"CDS module missing required fields: {missing}")
        return {
            "module_id": str(module["module_id"]),
            "name": str(module["name"]),
            "domain": str(module["domain"]),
            "purpose": str(module["purpose"]),
            "status": str(module["status"]),
            "inputs": self._split_csvish(module.get("inputs")),
            "outputs": self._split_csvish(module.get("outputs")),
            "dependencies": self._split_csvish(module.get("dependencies")),
            "next_action": module.get("next_action") or None,
            "runtime_state": self._runtime_state(module),
        }

    def _split_csvish(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [part.strip() for part in str(value).split(",") if part.strip()]

    def _runtime_state(self, module: dict[str, Any]) -> dict[str, Any]:
        status = str(module.get("status", "unknown"))
        if status == "live-ready":
            health = "ready"
        elif status == "framework":
            health = "scaffolded"
        elif status == "planned":
            health = "planned"
        else:
            health = "unknown"
        return {
            "health": health,
            "is_live_ready": status == "live-ready",
            "needs_implementation": status in {"framework", "planned"},
        }


@lru_cache(maxsize=1)
def get_cds_loader() -> CDSRegistryLoader:
    return CDSRegistryLoader()


def clear_cds_cache() -> None:
    get_cds_loader.cache_clear()
