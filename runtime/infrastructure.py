from __future__ import annotations

import time
import urllib.request
from typing import Any, Dict, List

from .config_loader import BrainConfigLoader, BrainConfigError


class InfrastructureRegistryService:
    """Reads infrastructure registry from the Brain and checks service health."""

    def __init__(self, loader: BrainConfigLoader | None = None) -> None:
        self.loader = loader or BrainConfigLoader()

    def registry(self) -> Dict[str, Any]:
        try:
            data = self.loader.load_infrastructure_registry()
            data["config_source"] = {
                "repo": self.loader.source.repo,
                "ref": self.loader.source.ref,
                "status": "loaded",
            }
            return data
        except BrainConfigError as exc:
            return {
                "registry_version": "unknown",
                "services": [],
                "config_source": {
                    "repo": self.loader.source.repo,
                    "ref": self.loader.source.ref,
                    "status": "error",
                    "error": str(exc),
                },
            }

    def _check_service(self, service: Dict[str, Any]) -> Dict[str, Any]:
        url = service.get("url") or ""
        health_path = service.get("health_path") or "/"
        status = service.get("status") or "unknown"

        result = {
            "service_key": service.get("service_key"),
            "display_name": service.get("display_name"),
            "role": service.get("role"),
            "configured_status": status,
            "url": url,
            "health_path": health_path,
            "runtime_status": "unknown",
            "message": "Not checked.",
            "status_code": None,
            "latency_ms": None,
        }

        if status in {"legacy_or_failed", "retired"}:
            result["runtime_status"] = "skipped"
            result["message"] = f"Service configured as {status}."
            return result

        if not url:
            result["runtime_status"] = "unknown"
            result["message"] = "No URL configured."
            return result

        health_url = url.rstrip("/") + "/" + health_path.lstrip("/")
        start = time.perf_counter()
        try:
            with urllib.request.urlopen(health_url, timeout=12) as response:
                code = response.getcode()
            latency_ms = round((time.perf_counter() - start) * 1000, 2)
            result["status_code"] = code
            result["latency_ms"] = latency_ms
            result["runtime_status"] = "healthy" if 200 <= code < 400 else "warning"
            result["message"] = f"HTTP {code}"
            return result
        except Exception as exc:
            latency_ms = round((time.perf_counter() - start) * 1000, 2)
            result["latency_ms"] = latency_ms
            result["runtime_status"] = "critical"
            result["message"] = str(exc)
            return result

    def health(self) -> Dict[str, Any]:
        registry = self.registry()
        services: List[Dict[str, Any]] = registry.get("services", [])
        checks = [self._check_service(s) for s in services]

        summary = {
            "healthy": sum(1 for c in checks if c["runtime_status"] == "healthy"),
            "warning": sum(1 for c in checks if c["runtime_status"] == "warning"),
            "critical": sum(1 for c in checks if c["runtime_status"] == "critical"),
            "unknown": sum(1 for c in checks if c["runtime_status"] == "unknown"),
            "skipped": sum(1 for c in checks if c["runtime_status"] == "skipped"),
            "total": len(checks),
        }

        if summary["critical"]:
            overall = "critical"
        elif summary["warning"] or summary["unknown"]:
            overall = "attention"
        else:
            overall = "healthy"

        return {
            "overall_status": overall,
            "summary": summary,
            "config_source": registry.get("config_source"),
            "services": checks,
        }
