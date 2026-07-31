from __future__ import annotations

import hashlib
import json
from uuid import UUID, uuid5

PUBLICATION_NAMESPACE = UUID("20c7f4fb-4eb9-5c24-a37c-1de31bc4683f")


def canonical_hash(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def publication_identity(payload: dict) -> tuple[str, str]:
    digest = canonical_hash(payload)
    return str(uuid5(PUBLICATION_NAMESPACE, digest)), digest
