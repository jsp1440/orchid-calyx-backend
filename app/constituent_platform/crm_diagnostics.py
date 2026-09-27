"""Administrator-visible CRM diagnostics.

Each check returns ``{"check", "status": ok|warning|error, "message", "action"}`` so a
society administrator (or the platform operator) can see what is wrong and what to
do next without reading source code. Checks report counts and names, never member
PII, SQL, connection strings, or secrets.

* ``platform_diagnostics`` (platform operator): database reachability, required
  schema, row-level security coverage, runtime role usability, legacy rows that
  still violate tenant constraints, societies without an administrator, lifecycle
  job health.
* ``organization_diagnostics`` (``diagnostics.read`` in that society): memberships
  the lifecycle job should already have moved, long-pending memberships, duplicate
  candidates, lifecycle job history, and any registered lane checks (payments,
  webhooks, imports) contributed through ``register_organization_check``.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg

from .authorization import SocietyCapability
from .postgres_repository import PostgresSocietyCRMRepository
from .society_service import CRMPrincipal, SocietyCRMService
from .tenant_db import RUNTIME_ROLE, platform_transaction, tenant_transaction

LIFECYCLE_JOB = "membership_lifecycle"
LIFECYCLE_MAX_AGE = timedelta(hours=36)
PENDING_TOO_LONG = timedelta(days=30)

REQUIRED_TABLES = (
    "oc_constituent.organizations",
    "oc_constituent.constituents",
    "oc_constituent.memberships",
    "oc_constituent.membership_levels",
    "oc_constituent.organization_staff_roles",
    "oc_constituent.organization_identity_bindings",
    "oc_constituent.membership_renewals",
    "oc_constituent.membership_household_members",
    "oc_constituent.external_record_links",
    "oc_constituent.crm_audit_events",
    "oc_constituent.member_portal_invites",
    "oc_constituent.crm_job_runs",
)

OrganizationCheck = Callable[[PostgresSocietyCRMRepository, int], list[dict[str, Any]]]
_ORGANIZATION_CHECKS: list[OrganizationCheck] = []


def register_organization_check(check: OrganizationCheck) -> OrganizationCheck:
    """Lanes (payments, imports, communications) add their own admin-facing checks."""
    if check not in _ORGANIZATION_CHECKS:
        _ORGANIZATION_CHECKS.append(check)
    return check


def _result(check: str, status: str, message: str, action: str = "", **details: Any) -> dict[str, Any]:
    return {"check": check, "status": status, "message": message, "action": action, **details}


def _database_down(check: str) -> dict[str, Any]:
    return _result(
        check, "error", "The CRM database could not be reached.",
        "Check the database provider status (Render/Neon dashboard). No member data was changed.",
    )


def platform_diagnostics(repo: PostgresSocietyCRMRepository, principal: CRMPrincipal) -> list[dict[str, Any]]:
    if not principal.platform_operator:
        raise PermissionError("PLATFORM_OPERATOR_REQUIRED")
    results: list[dict[str, Any]] = []
    try:
        started = time.monotonic()
        with platform_transaction(connect=repo._connect) as cur:
            cur.execute("SELECT 1")
            latency_ms = round((time.monotonic() - started) * 1000, 1)
            results.append(_result("database", "ok", f"Database reachable ({latency_ms} ms).", latency_ms=latency_ms))

            cur.execute(
                "SELECT n.nspname || '.' || c.relname AS name, c.relrowsecurity AS rls "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE c.relkind = 'r' AND n.nspname IN ('oc_constituent', 'oc_communications') "
                "AND EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = c.oid AND NOT a.attisdropped "
                "AND a.attname IN ('organization_id', 'owner_organization_id'))"
            )
            tables = {row["name"]: row["rls"] for row in cur.fetchall()}
            missing = [name for name in REQUIRED_TABLES if name not in tables and name != "oc_constituent.organizations"]
            if missing:
                results.append(_result(
                    "schema", "error", f"{len(missing)} required CRM table(s) are missing.",
                    "Apply the CRM migrations in order (see docs/operations/OC-CRM-BACKUP-RESTORE-001.md).",
                    missing=missing,
                ))
            else:
                results.append(_result("schema", "ok", "All required CRM tables are present."))
            without_rls = sorted(name for name, rls in tables.items() if not rls)
            results.append(
                _result("row_level_security", "error",
                        f"{len(without_rls)} CRM table(s) have row-level security disabled.",
                        "Re-apply the tenant isolation migration; do not enable the society CRM until fixed.",
                        tables=without_rls)
                if without_rls else
                _result("row_level_security", "ok", "Row-level security is enabled on every CRM table.")
            )

            cur.execute(
                "SELECT pg_has_role(current_user, %s, 'MEMBER') AS usable, "
                "EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %s) AS present",
                (RUNTIME_ROLE, RUNTIME_ROLE),
            )
            role = cur.fetchone()
            results.append(
                _result("runtime_role", "ok", "The backend can enter the CRM runtime role.")
                if role["present"] and role["usable"] else
                _result("runtime_role", "error", "The backend cannot enter the CRM runtime role.",
                        f"An operator must run: GRANT {RUNTIME_ROLE} TO <backend database login>;")
            )

            cur.execute(
                "SELECT conrelid::regclass::text AS table_name, conname FROM pg_constraint "
                "WHERE NOT convalidated AND connamespace = 'oc_constituent'::regnamespace ORDER BY 1, 2"
            )
            unvalidated = [dict(row) for row in cur.fetchall()]
            results.append(
                _result("legacy_tenant_rows", "warning",
                        f"{len(unvalidated)} tenant constraint(s) are not yet validated because older rows predate tenant ownership.",
                        "Reconcile legacy rows (assign an owning society) and re-apply the migration.",
                        constraints=unvalidated)
                if unvalidated else
                _result("legacy_tenant_rows", "ok", "All tenant constraints are validated.")
            )

            cur.execute(
                """
                SELECT o.slug FROM oc_constituent.organizations o
                WHERE o.kind = 'society' AND o.status = 'active' AND NOT EXISTS (
                    SELECT 1 FROM oc_constituent.organization_staff_roles r
                    JOIN oc_constituent.organization_identity_bindings b
                      ON b.organization_id = r.organization_id AND b.constituent_id = r.constituent_id
                     AND b.status = 'active'
                    WHERE r.organization_id = o.id AND r.role_code = 'admin' AND r.status = 'active')
                ORDER BY o.slug
                """
            )
            orphaned = [row["slug"] for row in cur.fetchall()]
            results.append(
                _result("society_admins", "warning",
                        f"{len(orphaned)} active society(ies) have no administrator who can sign in.",
                        "Use 'Bootstrap administrator' for each listed society.", societies=orphaned)
                if orphaned else
                _result("society_admins", "ok", "Every active society has a signed-in administrator.")
            )
    except psycopg.OperationalError:
        return [_database_down("database")]
    except psycopg.errors.UndefinedTable:
        return results + [_result("schema", "error", "The CRM schema is not installed.",
                                  "Apply the CRM migrations before enabling the society CRM.")]
    results.append(_lifecycle_job_check(repo, None))
    return results


def _lifecycle_job_check(repo: PostgresSocietyCRMRepository, organization_id: int | None) -> dict[str, Any]:
    try:
        runs = repo.latest_job_runs(job_name=LIFECYCLE_JOB, organization_id=organization_id, limit=1)
    except psycopg.errors.UndefinedTable:
        return _result("lifecycle_job", "error", "Job history is not available.", "Apply the portal/ops migration.")
    if not runs:
        return _result("lifecycle_job", "warning", "The membership lifecycle job has never run.",
                       "Schedule scripts/oc_crm_lifecycle_job.py daily (Render cron job).")
    last = runs[0]
    age = datetime.now(timezone.utc) - last["started_at"]
    if last["status"] == "failed":
        return _result("lifecycle_job", "error", f"The last membership lifecycle run failed ({last['error_code']}).",
                       "Check the job log in Render; the job is safe to re-run.", last_run=last["started_at"])
    if age > LIFECYCLE_MAX_AGE:
        return _result("lifecycle_job", "warning",
                       f"The membership lifecycle job last ran {int(age.total_seconds() // 3600)} hours ago.",
                       "Check that the daily Render cron job is enabled.", last_run=last["started_at"])
    return _result("lifecycle_job", "ok", "The membership lifecycle job ran recently.", last_run=last["started_at"])


def organization_diagnostics(
    crm: SocietyCRMService, principal: CRMPrincipal, organization_id: int, *, as_of: datetime | None = None
) -> list[dict[str, Any]]:
    crm._require(organization_id, principal, SocietyCapability.DIAGNOSTICS_READ)
    repo: PostgresSocietyCRMRepository = crm._repo
    now = as_of or datetime.now(timezone.utc)
    results: list[dict[str, Any]] = []
    try:
        with tenant_transaction(organization_id, connect=repo._connect) as cur:
            cur.execute(
                """
                SELECT count(*) FILTER (WHERE m.status = 'active' AND m.expires_at <= %s) AS overdue_grace,
                       count(*) FILTER (WHERE m.status = 'grace'
                                          AND m.expires_at + make_interval(days => l.grace_days) <= %s) AS overdue_lapse,
                       count(*) FILTER (WHERE m.status = 'pending' AND m.created_at <= %s) AS stale_pending
                FROM oc_constituent.memberships m
                JOIN oc_constituent.membership_levels l
                  ON l.organization_id = m.organization_id AND l.code = m.level_code
                WHERE m.organization_id = %s
                """,
                (now, now, now - PENDING_TOO_LONG, organization_id),
            )
            counts = cur.fetchone()
    except psycopg.OperationalError:
        return [_database_down("database")]
    overdue = int(counts["overdue_grace"]) + int(counts["overdue_lapse"])
    results.append(
        _result("membership_lifecycle", "warning",
                f"{overdue} membership(s) are past their expiry or grace date but have not been moved.",
                "Run 'Update membership statuses' now; if this recurs, the daily lifecycle job is not running.",
                count=overdue)
        if overdue else
        _result("membership_lifecycle", "ok", "Membership statuses are up to date.")
    )
    stale = int(counts["stale_pending"])
    results.append(
        _result("pending_memberships", "warning",
                f"{stale} membership(s) have been pending for more than 30 days.",
                "Record their payment or renewal, or cancel them with a reason.", count=stale)
        if stale else
        _result("pending_memberships", "ok", "No long-pending memberships.")
    )
    duplicates = repo.duplicate_candidates(organization_id=organization_id)
    results.append(
        _result("duplicates", "warning", f"{len(duplicates)} possible duplicate member group(s) found.",
                "Review the Duplicates page and merge or annotate them.", count=len(duplicates))
        if duplicates else
        _result("duplicates", "ok", "No duplicate candidates.")
    )
    results.append(_lifecycle_job_check(repo, organization_id))
    for check in _ORGANIZATION_CHECKS:
        try:
            results.extend(check(repo, organization_id))
        except psycopg.OperationalError:
            results.append(_database_down(getattr(check, "__name__", "lane_check")))
        except psycopg.errors.UndefinedTable:
            results.append(_result(getattr(check, "__name__", "lane_check"), "error",
                                   "A CRM feature's tables are not installed.", "Apply the pending CRM migrations."))
    return results


def run_lifecycle_job(repo: PostgresSocietyCRMRepository, *, as_of: datetime | None = None) -> dict[str, Any]:
    """Daily job: apply time-based transitions for every active society. Idempotent."""
    run_id = repo.start_job_run(job_name=LIFECYCLE_JOB)
    summary: dict[str, Any] = {"societies": 0, "transitions": 0, "failed_societies": 0}
    failures: list[str] = []
    for org in repo.list_organizations():
        if org["kind"] != "society" or org["status"] != "active":
            continue
        summary["societies"] += 1
        try:
            changes = repo.apply_lifecycle(organization_id=int(org["id"]), as_of=as_of)
            summary["transitions"] += len(changes)
        except Exception as exc:  # one society's failure must not stop the others
            summary["failed_societies"] += 1
            failures.append(f"{org['slug']}:{type(exc).__name__}")
    ok = not failures
    repo.finish_job_run(run_id, succeeded=ok, summary={**summary, "failures": failures},
                        error_code=None if ok else "SOCIETY_LIFECYCLE_FAILED")
    return {"run_id": run_id, "succeeded": ok, **summary, "failures": failures}
