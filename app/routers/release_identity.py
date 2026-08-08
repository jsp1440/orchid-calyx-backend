from __future__ import annotations

import os
import re

from fastapi import APIRouter

router = APIRouter(tags=["release-identity"])

_FULL_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_RELEASE_SHA_ENV_KEYS = (
    "OCU_RELEASE_SHA",
    "RENDER_GIT_COMMIT",
    "GIT_COMMIT",
    "COMMIT_SHA",
)


def deployed_commit_sha() -> tuple[str | None, str | None]:
    """Resolve a non-secret deployed Git commit identity without inventing one."""
    for key in _RELEASE_SHA_ENV_KEYS:
        value = os.getenv(key, "").strip().lower()
        if value:
            return value, key
    return None, None


def release_identity() -> dict[str, object]:
    sha, source = deployed_commit_sha()
    valid = bool(sha and _FULL_GIT_SHA.fullmatch(sha))
    return {
        "contract": "OCU-RELEASE-IDENTITY-001",
        "service": "orchid-calyx-backend",
        "commit_sha": sha if valid else None,
        "attested": valid,
        "source": source,
    }


@router.get("/api/release-identity")
def get_release_identity():
    return release_identity()
