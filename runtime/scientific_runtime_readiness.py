"""Runtime dependency readiness for CALYX-617 without importing optional libraries."""
from __future__ import annotations

import platform
import sys
from importlib.metadata import PackageNotFoundError, version
from importlib.util import find_spec
from typing import Any

SCIENTIFIC_PYTHON_MINIMUM = (3, 12)
SCIENTIFIC_PYTHON_MINIMUM_TEXT = "3.12"
MEAN_CI_SCIPY_REQUIRED_VERSION = "1.18.0"
SCIENTIFIC_DEPENDENCY_PROFILE = "requirements-scientific.txt"


def _installed_version(package: str) -> str | None:
    if find_spec(package) is None:
        return None
    try:
        return version(package)
    except PackageNotFoundError:
        return None


def scientific_runtime_readiness() -> dict[str, Any]:
    """Describe whether this process satisfies the non-live mean-CI dependency gate."""
    scipy_version = _installed_version("scipy")
    python_compatible = sys.version_info[:2] >= SCIENTIFIC_PYTHON_MINIMUM
    scipy_compatible = scipy_version == MEAN_CI_SCIPY_REQUIRED_VERSION
    return {
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "required_python_minimum": SCIENTIFIC_PYTHON_MINIMUM_TEXT,
        "python_compatible": python_compatible,
        "scientific_dependency_profile": SCIENTIFIC_DEPENDENCY_PROFILE,
        "scipy_required_version": MEAN_CI_SCIPY_REQUIRED_VERSION,
        "scipy_available": scipy_version is not None,
        "scipy_version": scipy_version,
        "scipy_compatible": scipy_compatible,
        "mean_ci_candidate_dependency_ready": python_compatible and scipy_compatible,
        "mean_ci_live_method_registered": False,
        "readiness_is_dependency_state_not_publication_authority": True,
    }
