"""Project a real University module into Calyx's presentation-only contract."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .contract import ContractViolation

UNIVERSITY_MODULE_PATH = "app/university/ai_data_science.py"


def from_university_module(module: Mapping[str, Any]) -> dict[str, Any]:
    """Build a bounded, locality-free artifact from the registered module record."""
    module_id = module.get("module_id")
    module_version = module.get("module_version")
    title = module.get("title")
    objectives = module.get("learning_objectives")
    if not all(isinstance(value, str) and value.strip() for value in (module_id, module_version, title)):
        raise ContractViolation("UNIVERSITY_MODULE_IDENTITY_REQUIRED")
    if not isinstance(objectives, list) or any(not isinstance(item, str) for item in objectives):
        raise ContractViolation("UNIVERSITY_MODULE_OBJECTIVES_REQUIRED")

    artifact_id = f"university-module:{module_id}@{module_version}"
    return {
        "artifact_id": artifact_id,
        "source_module": {
            "path": UNIVERSITY_MODULE_PATH,
            "module_id": module_id,
            "module_version": module_version,
            "title": title,
            "learning_objectives": list(objectives),
        },
        "claims": [],
        "surfaces": [
            {
                "id": artifact_id,
                "claim_ids": [],
                "reading_level": module.get("reading_level"),
            }
        ],
    }
