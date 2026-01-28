from __future__ import annotations

import os
from typing import Optional

from fastapi import Header, HTTPException


def require_admin(x_orchid_admin_key: Optional[str] = Header(default=None, alias="X-Orchid-Admin-Key")) -> None:
    admin_key = os.getenv("ORCHID_JUDGE_ADMIN_KEY")
    if not admin_key:
        raise HTTPException(status_code=500, detail="Server missing ORCHID_JUDGE_ADMIN_KEY env var.")
    if x_orchid_admin_key != admin_key:
        raise HTTPException(status_code=401, detail="Invalid admin key.")
