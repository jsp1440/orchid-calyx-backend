from __future__ import annotations
import os
import urllib.request
from typing import List
from .models import HealthCheckResult


class HealthMonitorService:
    """Read-only health checks for Active Calyx."""

    def __init__(self, backend_url: str | None = None, frontend_url: str | None = None) -> None:
        self.backend_url = backend_url or os.getenv("CALYX_BACKEND_URL", "")
        self.frontend_url = frontend_url or os.getenv("CALYX_FRONTEND_URL", "")

    def _check_url(self, name: str, url: str) -> HealthCheckResult:
        if not url:
            return HealthCheckResult(name, "unknown", "No URL configured.")

        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                code = response.getcode()
            status = "healthy" if 200 <= code < 400 else "warning"
            return HealthCheckResult(
                name,
                status,
                f"HTTP {code}",
                details={"url": url, "status_code": code},
            )
        except Exception as exc:
            return HealthCheckResult(name, "critical", str(exc), details={"url": url})

    def run(self) -> List[HealthCheckResult]:
        checks = [
            self._check_url("backend", self.backend_url),
            self._check_url("frontend", self.frontend_url),
        ]
        database_url = os.getenv("DATABASE_URL")
        checks.append(
            HealthCheckResult(
                "database_config",
                "configured" if database_url else "unknown",
                "DATABASE_URL configured." if database_url else "DATABASE_URL not configured.",
            )
        )
        return checks
