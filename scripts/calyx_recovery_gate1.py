"""Gate 1 of CALYX-RECOVERY-001: read-only recovery baseline.

SELECT statements only. This script never writes, never migrates, never
activates, and never prints a connection string or any credential — it reports
the database's identity by name and host only, which is what a receipt needs.

Every field is classified WORKING / DEGRADED / BLOCKED / UNKNOWN. A field that
could not be measured is UNKNOWN, never zero: "we could not look" and "there
is nothing there" are different statements, and only one of them is about the
Continuum's data.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Run as a script from anywhere: the repository root has to be importable for
# the reader and adapter modules this reuses, and CI invokes it by path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

WORKING = "WORKING"
DEGRADED = "DEGRADED"
BLOCKED = "BLOCKED"
UNKNOWN = "UNKNOWN"

#: (label, schema-qualified relation) for the coverage counts Gate 1 asks for.
#: Counted only if the relation exists; a missing relation is UNKNOWN, because
#: this script cannot tell "not deployed here" from "named differently".
COVERAGE_TARGETS = (
    ("build051_research_requests", "oc_admin", "build051_research_requests"),
    ("research_station_records", "oc_admin", "research_station_records"),
    ("artifact_registry", "oc_admin", "calyx_artifacts"),
)

#: Scientific domains, probed through the relation candidates the repository
#: already maintains in runtime.scientific_intelligence.adapters. Reusing them
#: keeps one definition of where a domain lives; a second list here would drift
#: from the readers that actually query it.
SCIENTIFIC_DOMAINS = (
    "taxonomy",
    "occurrences",
    "geography",
    "elevation",
    "literature",
    "pollinators",
    "mycorrhiza",
)

#: Columns whose presence answers the geography/elevation questions directly.
GEOMETRY_COLUMNS = ("decimal_latitude", "latitude", "lat")
ELEVATION_COLUMNS = ("elevation", "elevation_m", "elevation_metres", "altitude")


def _classify(available: bool, present: bool) -> str:
    """Absent is UNKNOWN, never DEGRADED.

    This script cannot tell "not deployed here" from "named differently", and
    reporting a relation it could not find as a degraded capability would be
    stating something it has not established.
    """
    if not available:
        return BLOCKED
    return WORKING if present else UNKNOWN


def _static_fields(fields: dict) -> None:
    """Fields measurable without a database, so they are never left UNKNOWN."""
    fields["deployed_release_identity"] = {
        # This script runs in CI against a checkout, so it can attest the SHA
        # it ran from. Whether the deployment is serving that SHA is a
        # different question and is not answered here.
        "state": WORKING if os.environ.get("GITHUB_SHA") else UNKNOWN,
        "repository_sha": os.environ.get("GITHUB_SHA", UNKNOWN),
        "detail": "repository SHA this receipt was produced from; not the served SHA",
    }
    try:
        from runtime.research_executor_worker import executor_readiness

        fields["executor_readiness"] = {"state": WORKING, **executor_readiness()}
    except Exception as exc:
        fields["executor_readiness"] = {
            "state": UNKNOWN,
            "detail": f"{type(exc).__name__}: {exc}",
        }


def _probe_graph(cur) -> dict:
    """Persisted graph nodes/edges, if any candidate relation exists."""
    try:
        from runtime.scientific_intelligence import adapters as a
    except Exception as exc:
        return {"state": UNKNOWN, "detail": f"adapters unavailable: {exc}"}

    found: dict[str, object] = {}
    for label, candidates in (
        ("nodes", a._KG_ENTITY_CANDIDATES),
        ("edges", a._KG_RELATIONSHIP_CANDIDATES),
    ):
        for relation in candidates:
            cur.execute("SELECT to_regclass(%s) AS reg", (relation,))
            if (cur.fetchone() or {}).get("reg") is None:
                continue
            schema, _, table = relation.partition(".")
            from psycopg import sql as psycopg_sql

            cur.execute(
                psycopg_sql.SQL("SELECT COUNT(*) AS n FROM {}.{}").format(
                    psycopg_sql.Identifier(schema), psycopg_sql.Identifier(table)
                )
            )
            found[label] = {"relation": relation, "row_count": int((cur.fetchone() or {}).get("n", 0))}
            break
        else:
            found[label] = {"state": UNKNOWN, "detail": "no candidate relation found"}
    return {"state": WORKING if "relation" in str(found) else UNKNOWN, **found}


def _probe_domain(cur, domain: str) -> dict:
    """Row counts and column presence for one scientific domain."""
    try:
        from runtime.scientific_intelligence import adapters as a
        from runtime.scientific_readers import _candidates
    except Exception as exc:
        return {"state": UNKNOWN, "detail": f"reader module unavailable: {exc}"}

    candidates = _candidates().get(domain, ())
    for relation in candidates:
        cur.execute("SELECT to_regclass(%s) AS reg", (relation,))
        if (cur.fetchone() or {}).get("reg") is None:
            continue
        schema, _, table = relation.partition(".")
        cur.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            """,
            (schema, table),
        )
        columns = {str(row["column_name"]).lower() for row in cur.fetchall()}
        from psycopg import sql as psycopg_sql

        cur.execute(
            psycopg_sql.SQL("SELECT COUNT(*) AS n FROM {}.{}").format(
                psycopg_sql.Identifier(schema), psycopg_sql.Identifier(table)
            )
        )
        rows = int((cur.fetchone() or {}).get("n", 0))
        entry = {
            "state": WORKING if rows else DEGRADED,
            "relation": relation,
            "row_count": rows,
        }
        if domain in {"occurrences", "geography"}:
            entry["has_coordinates"] = bool(columns & set(GEOMETRY_COLUMNS))
        if domain == "elevation":
            entry["has_elevation"] = bool(columns & set(ELEVATION_COLUMNS))
        if not rows:
            entry["detail"] = "relation exists but holds no rows"
        return entry

    # No candidate relation exists. That is not "no data" — this schema does
    # not carry the domain under any name this repository knows.
    return {
        "state": UNKNOWN,
        "detail": f"no relation found among {len(candidates)} known candidates",
        "candidates_probed": len(candidates),
    }


def main() -> int:
    started = datetime.now(timezone.utc).isoformat()
    receipt: dict[str, object] = {
        "gate": "CALYX-RECOVERY-001/gate-1",
        "generated_at": started,
        "repository_sha": os.environ.get("GITHUB_SHA", UNKNOWN),
        "read_only": True,
        "fields": {},
    }
    fields: dict[str, object] = receipt["fields"]  # type: ignore[assignment]

    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        fields["database_connectivity"] = {
            "state": BLOCKED,
            "detail": "DATABASE_URL is not configured for this run",
        }
        # Everything downstream is unmeasurable, and says so rather than zero.
        for label, _, _ in COVERAGE_TARGETS:
            fields[label] = {"state": UNKNOWN, "detail": "no database connection"}
        for domain in SCIENTIFIC_DOMAINS:
            fields[f"domain_{domain}"] = {
                "state": UNKNOWN,
                "detail": "no database connection",
            }
        _static_fields(fields)
        json.dump(receipt, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0

    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        fields["database_connectivity"] = {
            "state": BLOCKED,
            "detail": f"psycopg unavailable: {exc}",
        }
        json.dump(receipt, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0

    try:
        with psycopg.connect(url, row_factory=dict_row, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                # Identity by name only. The connection string never appears.
                cur.execute(
                    "SELECT current_database() AS db, current_user AS usr, version() AS v"
                )
                identity = cur.fetchone() or {}
                fields["database_connectivity"] = {"state": WORKING}
                fields["database_identity"] = {
                    "state": WORKING,
                    "database": identity.get("db"),
                    "user": identity.get("usr"),
                    "server_version": str(identity.get("v", ""))[:40],
                }

                for label, schema, table in COVERAGE_TARGETS:
                    cur.execute(
                        """
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.tables
                            WHERE table_schema = %s AND table_name = %s
                        ) AS present
                        """,
                        (schema, table),
                    )
                    present = bool((cur.fetchone() or {}).get("present"))
                    entry: dict[str, object] = {
                        "state": _classify(True, present),
                        "relation": f"{schema}.{table}",
                        "present": present,
                    }
                    if present:
                        cur.execute(f"SELECT COUNT(*) AS n FROM {schema}.{table}")
                        entry["row_count"] = int((cur.fetchone() or {}).get("n", 0))
                    else:
                        # Absent relation: the row count is unknown, not zero.
                        entry["row_count"] = None
                        entry["detail"] = "relation not found in this database"
                    fields[label] = entry

                # Request states, so the executor's queue depth is measurable
                # without reading any request's content.
                if fields.get("build051_research_requests", {}).get("present"):  # type: ignore[union-attr]
                    cur.execute(
                        """
                        SELECT payload->>'status' AS status, COUNT(*) AS n
                        FROM oc_admin.build051_research_requests
                        GROUP BY 1 ORDER BY 1
                        """
                    )
                    fields["research_request_states"] = {
                        "state": WORKING,
                        "counts": {
                            str(row["status"]): int(row["n"]) for row in cur.fetchall()
                        },
                    }
                else:
                    fields["research_request_states"] = {
                        "state": UNKNOWN,
                        "detail": "request table not present",
                    }

                for domain in SCIENTIFIC_DOMAINS:
                    fields[f"domain_{domain}"] = _probe_domain(cur, domain)

                # Persisted graph against canonical sources, where both are
                # measurable. Neither number is a completeness claim: an
                # unmaterialised graph does not mean the database lacks data,
                # and a materialised one is not a survey.
                fields["knowledge_graph_materialization"] = _probe_graph(cur)
    except Exception as exc:
        # The exception type and message only. A psycopg error can carry the
        # host; the class name and a truncated message do not carry secrets.
        fields["database_connectivity"] = {
            "state": BLOCKED,
            "detail": f"{type(exc).__name__}",
        }
        for label, _, _ in COVERAGE_TARGETS:
            fields.setdefault(label, {"state": UNKNOWN, "detail": "connection failed"})

    _static_fields(fields)
    json.dump(receipt, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
