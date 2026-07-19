from __future__ import annotations

from time import monotonic
from typing import Any

from .drive import DriveGateway, walk_drive
from .models import ScanResult


class SourceScanService:
    def __init__(self, repository: Any, gateway: DriveGateway):
        self.repository = repository
        self.gateway = gateway

    def scan(self, source_id: str, folder_ids: list[str]) -> ScanResult:
        started = monotonic()
        scan_id = self.repository.start_scan(source_id)
        discovered = processed = unchanged = duplicates = failed = 0
        errors: list[str] = []
        try:
            for file in walk_drive(self.gateway, folder_ids):
                discovered += 1
                try:
                    outcome = self.repository.inventory_file(source_id, scan_id, file)
                    unchanged += int(outcome == "UNCHANGED")
                    duplicates += int(outcome == "DUPLICATE")
                    processed += int(outcome != "UNCHANGED")
                except Exception as exc:
                    failed += 1
                    errors.append(f"{file.file_id}: {exc}"[:500])
            status = "COMPLETED" if failed == 0 else "COMPLETED_WITH_ERRORS"
            self.repository.finish_scan(
                scan_id, source_id, status, processed, unchanged, duplicates, failed,
                "; ".join(errors)[:2000] or None,
            )
        except Exception as exc:
            self.repository.finish_scan(scan_id, source_id, "FAILED", processed, unchanged, duplicates, failed + 1, str(exc)[:2000])
            raise
        return ScanResult(source_id, scan_id, discovered, processed, unchanged, duplicates, failed, int((monotonic()-started)*1000))
