"""The ordered society CRM migration chain (single source of truth).

Tests, the CI workflow (``CRM_MIGRATIONS`` in
``.github/workflows/oc-society-crm-p0-validation.yml``, checked by
``tests/test_society_crm_domain.py``), and operators applying the schema use this
order. Every file is idempotent and must re-apply cleanly.
"""

from __future__ import annotations

from pathlib import Path

import psycopg

REPO_ROOT = Path(__file__).resolve().parents[2]

CRM_MIGRATIONS: tuple[str, ...] = (
    "migrations/20260823_oc_constituent_communications_foundation.sql",
    "migrations/20260926_society_crm_p0_core.sql",
    "migrations/20260927_society_crm_p1_tenant_isolation.sql",
    "migrations/20260927b_constituent_newsletter_canonical.sql",
    "migrations/20260927c_society_crm_portal_ops.sql",
    "migrations/20260927d_society_crm_communications.sql",
    "migrations/20260928_society_crm_money.sql",
)


def apply_crm_migrations(dsn: str, *, twice: bool = False) -> None:
    """Apply the chain in order (optionally twice, proving idempotency)."""
    with psycopg.connect(dsn, autocommit=True) as conn:
        for _ in range(2 if twice else 1):
            for relative in CRM_MIGRATIONS:
                conn.execute((REPO_ROOT / relative).read_text(encoding="utf-8"))
