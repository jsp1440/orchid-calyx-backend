"""Domain source providers.

The orchestrator reads a domain's *canonical relational rows* through a
:class:`SourceProvider`.  This keeps the orchestrator agnostic of where rows
come from:

* :class:`InMemorySourceProvider` is used by tests and dry runs — it never
  opens a database connection, guaranteeing "no production reads/writes during
  tests";
* :class:`PostgresSourceProvider` issues **read-only** ``SELECT`` statements
  against the canonical source tables registered in :mod:`domain_sources`.  It
  is only constructed for a live audit/publish run and is never exercised by
  the test suite.

Rows are plain dicts.  Each row is expected to carry at least ``source_pk``
(the domain object's primary key) and ``taxon_pk`` (the taxon it attaches to);
adapters read the remaining fields they need.
"""

from __future__ import annotations

from typing import Any, Iterable, Iterator, Protocol


class SourceProvider(Protocol):
    def count(self, domain: str) -> int: ...
    def fetch(self, domain: str, batch_size: int, offset: int) -> list[dict[str, Any]]: ...


class InMemorySourceProvider:
    """A pure-Python source of domain rows for tests and offline dry runs."""

    def __init__(self, rows_by_domain: dict[str, list[dict[str, Any]]] | None = None):
        self._rows: dict[str, list[dict[str, Any]]] = {
            k: list(v) for k, v in (rows_by_domain or {}).items()
        }

    def add(self, domain: str, rows: Iterable[dict[str, Any]]) -> None:
        self._rows.setdefault(domain, []).extend(rows)

    def domains(self) -> list[str]:
        return sorted(self._rows)

    def count(self, domain: str) -> int:
        return len(self._rows.get(domain, ()))

    def fetch(self, domain: str, batch_size: int, offset: int) -> list[dict[str, Any]]:
        rows = self._rows.get(domain, ())
        return list(rows[offset: offset + batch_size])

    def batches(self, domain: str, batch_size: int) -> Iterator[list[dict[str, Any]]]:
        offset = 0
        while True:
            chunk = self.fetch(domain, batch_size, offset)
            if not chunk:
                return
            yield chunk
            offset += batch_size


class PostgresSourceProvider:
    """Read-only row provider over the canonical source tables.

    This issues only ``SELECT`` statements.  It performs NO writes and is not
    used by the test suite (tests use :class:`InMemorySourceProvider`).  The
    concrete per-domain projection SQL lives in ``queries`` so operators can
    review/override exactly what is read before any live run.
    """

    def __init__(self, dsn: str, queries: dict[str, str], *, validate: bool = True):
        from .source_registry import assert_safe_sql

        self._dsn = dsn
        self._queries = dict(queries)
        if validate:
            for domain, sql in self._queries.items():
                assert_safe_sql(sql)

    @classmethod
    def from_registry(cls, dsn: str) -> "PostgresSourceProvider":
        """Build a provider from the config-driven source-query registry.

        This is the only supported way to run against production: the registry
        is the single place per-domain read-only SQL lives.
        """
        from .source_registry import enabled_queries

        return cls(dsn, enabled_queries())

    def _connect(self):
        import psycopg  # lazy import so tests never require a driver/DB
        return psycopg.connect(self._dsn, connect_timeout=5)

    def _base_query(self, domain: str) -> str:
        from .source_registry import assert_safe_sql

        if domain not in self._queries:
            raise KeyError(f"no read-only source query registered for domain {domain!r}")
        sql = self._queries[domain]
        assert_safe_sql(sql)
        return sql.rstrip().rstrip(";")

    def count(self, domain: str) -> int:
        sql = f"SELECT count(*) FROM ({self._base_query(domain)}) AS _src"
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql)
            row = cur.fetchone()
            return int(row[0]) if row else 0

    def fetch(self, domain: str, batch_size: int, offset: int) -> list[dict[str, Any]]:
        sql = (
            f"SELECT * FROM ({self._base_query(domain)}) AS _src "
            f"ORDER BY source_pk LIMIT %s OFFSET %s"
        )
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql, (batch_size, offset))
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
