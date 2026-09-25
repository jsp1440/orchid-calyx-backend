"""Runtime dependency readiness for CALYX-617 without importing optional libraries."""
from __future__ import annotations

import platform
import re
import sys
from importlib.metadata import PackageNotFoundError, version
from importlib.util import find_spec
from pathlib import Path
from typing import Any

SCIENTIFIC_PYTHON_MINIMUM = (3, 12)
SCIENTIFIC_PYTHON_MINIMUM_TEXT = "3.12"
SCIENTIFIC_DEPENDENCY_PROFILE = "requirements-scientific.txt"
SCIENTIFIC_DEPENDENCY_PROFILE_PATH = (
    Path(__file__).resolve().parents[1] / SCIENTIFIC_DEPENDENCY_PROFILE
)
_SCIPY_PIN = re.compile(
    r"^\s*scipy\s*==\s*([0-9][0-9A-Za-z.]*)\s*(?:#.*)?$", re.MULTILINE
)


def required_scipy_version(
    profile_path: Path = SCIENTIFIC_DEPENDENCY_PROFILE_PATH,
) -> str | None:
    """Return the exact ``scipy==`` pin declared by the scientific dependency profile.

    The profile file is the single source of truth for the validated SciPy build.
    A missing profile or a profile without an exact pin yields ``None`` so that
    readiness fails closed instead of drifting to an unvalidated version.
    """
    try:
        text = profile_path.read_text(encoding="utf-8")
    except OSError:
        return None
    pins = _SCIPY_PIN.findall(text)
    if len(pins) != 1:
        return None
    return pins[0]


MEAN_CI_SCIPY_REQUIRED_VERSION = required_scipy_version()


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
    scipy_compatible = (
        MEAN_CI_SCIPY_REQUIRED_VERSION is not None
        and scipy_version == MEAN_CI_SCIPY_REQUIRED_VERSION
    )
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
