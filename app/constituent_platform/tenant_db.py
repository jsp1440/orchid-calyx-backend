"""Transaction-scoped tenant context for the society CRM.

Every society-owned read or write runs inside ``tenant_transaction``:

* ``SET LOCAL ROLE oc_crm_runtime`` -- the NOLOGIN role the RLS policies apply to;
* ``set_config('oc.crm_organization_id', <id>, true)`` -- the tenant, transaction-local.

Both are discarded at COMMIT or ROLLBACK, so a pooled connection handed to the next
request carries neither the role nor the tenant. With no tenant set, every CRM policy
matches no rows (default deny).

This is defence in depth beneath the explicit ``organization_id`` filters in the
repository: a query that forgets its tenant filter still cannot see another tenant.
It is not an authentication boundary; the backend chooses the tenant only after it
has authenticated the caller and authorized the capability.

``platform_transaction`` is for the few platform-operator operations that are not
tenant-owned (creating an organization, resolving a slug). It does not enter the
runtime role.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row

RUNTIME_ROLE = "oc_crm_runtime"
TENANT_SETTING = "oc.crm_organization_id"

ConnectionFactory = Callable[[], psycopg.Connection]


def database_url() -> str:
    value = os.environ.get("DATABASE_URL")
    if not value:
        raise RuntimeError("DATABASE_URL is required for society CRM operations")
    return value


def dsn_connection_factory(dsn: str | None = None) -> ConnectionFactory:
    resolved = dsn or database_url()

    def connect() -> psycopg.Connection:
        return psycopg.connect(resolved, row_factory=dict_row)

    return connect


def _validated_tenant(organization_id: Any) -> int:
    if isinstance(organization_id, bool) or not isinstance(organization_id, int) or organization_id < 1:
        raise ValueError("TENANT_ORGANIZATION_ID_REQUIRED")
    return organization_id


@contextmanager
def _transaction(
    connect: ConnectionFactory,
    connection: psycopg.Connection | None,
) -> Iterator[tuple[psycopg.Connection, psycopg.Cursor]]:
    owned = connection is None
    conn = connection if connection is not None else connect()
    try:
        with conn.transaction():
            with conn.cursor(row_factory=dict_row) as cur:
                yield conn, cur
    finally:
        if owned:
            conn.close()


def _outer_tenant(connection: psycopg.Connection | None) -> str | None:
    """Tenant already set by an enclosing transaction on this connection, if any.

    ``SET LOCAL`` inside a savepoint survives RELEASE until the outer transaction
    ends, so a nested block must never switch tenant (or drop to platform scope)
    on a connection whose outer transaction is bound to a tenant.
    """
    if connection is None or connection.info.transaction_status == psycopg.pq.TransactionStatus.IDLE:
        return None
    with connection.cursor() as probe:
        probe.execute("SELECT current_setting(%s, true)", (TENANT_SETTING,))
        row = probe.fetchone()
    value = row[0] if not isinstance(row, dict) else next(iter(row.values()))
    return value or None


@contextmanager
def tenant_transaction(
    organization_id: int,
    *,
    connect: ConnectionFactory,
    connection: psycopg.Connection | None = None,
) -> Iterator[psycopg.Cursor]:
    """One transaction bound to exactly one tenant, under the RLS runtime role."""
    tenant = _validated_tenant(organization_id)
    outer = _outer_tenant(connection)
    if outer is not None and outer != str(tenant):
        raise RuntimeError("CRM_NESTED_TENANT_MISMATCH")
    with _transaction(connect, connection) as (_conn, cur):
        cur.execute(f"SET LOCAL ROLE {RUNTIME_ROLE}")
        cur.execute("SELECT set_config(%s, %s, true)", (TENANT_SETTING, str(tenant)))
        yield cur


@contextmanager
def platform_transaction(
    *,
    connect: ConnectionFactory,
    connection: psycopg.Connection | None = None,
) -> Iterator[psycopg.Cursor]:
    """One transaction for platform-level (non-tenant) operations."""
    if _outer_tenant(connection) is not None:
        raise RuntimeError("CRM_PLATFORM_INSIDE_TENANT_TRANSACTION")
    with _transaction(connect, connection) as (_conn, cur):
        yield cur
