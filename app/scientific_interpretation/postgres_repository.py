from __future__ import annotations

from typing import Any, ClassVar

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


class PostgresInterpretationRepository:
    """Append-only PostgreSQL repository for BUILD-087 scientific artifacts."""

    TABLES: ClassVar[dict[str, tuple[str, str, str]]] = {
        "packet": ("evidence_packets", "packet_id", "packet_key"),
        "interpretation": ("machine_interpretations", "interpretation_id", "interpretation_key"),
        "assertion": ("canonical_assertions", "assertion_id", "assertion_key"),
        "correction": ("correction_records", "correction_id", "correction_key"),
    }

    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("DATABASE_URL_REQUIRED")
        self.database_url = database_url

    def _connect(self):
        return psycopg.connect(self.database_url, row_factory=dict_row, connect_timeout=10)

    @staticmethod
    def _record(row: dict[str, Any] | None) -> dict[str, Any] | None:
        if not row:
            return None
        payload = dict(row.pop("payload"))
        payload.update(row)
        for key, value in list(payload.items()):
            if hasattr(value, "isoformat"):
                payload[key] = value.isoformat()
        return payload

    def _by(self, kind: str, field: str, value: Any) -> dict[str, Any] | None:
        table, _, _ = self.TABLES[kind]
        if field not in {"fingerprint", self.TABLES[kind][1]}:
            raise ValueError("UNSAFE_LOOKUP_FIELD")
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(f"SELECT * FROM oc_scientific_interpretation.{table} WHERE {field}=%s ORDER BY version DESC LIMIT 1", (value,))
            return self._record(cursor.fetchone())

    def _save(self, kind: str, record: dict[str, Any]) -> dict[str, Any]:
        table, _id_field, key_field = self.TABLES[kind]
        logical_key = record[key_field]
        fingerprint = record.get("fingerprint")
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 87))", (f"{kind}:{logical_key}",))
            if fingerprint:
                cursor.execute(f"SELECT * FROM oc_scientific_interpretation.{table} WHERE fingerprint=%s", (fingerprint,))
                existing = cursor.fetchone()
                if existing:
                    return self._record(existing)  # type: ignore[return-value]
            cursor.execute(f"SELECT COALESCE(MAX(version),0)+1 AS version FROM oc_scientific_interpretation.{table} WHERE {key_field}=%s", (logical_key,))
            version = cursor.fetchone()["version"]
            cursor.execute(
                f"INSERT INTO oc_scientific_interpretation.{table}({key_field},version,fingerprint,payload) VALUES(%s,%s,%s,%s) RETURNING *",
                (logical_key, version, fingerprint, Jsonb(record)),
            )
            return self._record(cursor.fetchone())  # type: ignore[return-value]

    def packet_by_fingerprint(self, fingerprint: str) -> dict[str, Any] | None:
        return self._by("packet", "fingerprint", fingerprint)

    def packets_by_ids(self, packet_ids: tuple[int, ...]) -> list[dict[str, Any]]:
        if not packet_ids:
            return []
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT * FROM oc_scientific_interpretation.evidence_packets WHERE packet_id=ANY(%s) ORDER BY packet_id", (list(packet_ids),))
            return [self._record(row) for row in cursor.fetchall()]  # type: ignore[misc]

    def save_packet(self, record: dict[str, Any]) -> dict[str, Any]:
        return self._save("packet", record)

    def interpretation_by_fingerprint(self, fingerprint: str) -> dict[str, Any] | None:
        return self._by("interpretation", "fingerprint", fingerprint)

    def interpretation(self, interpretation_id: int) -> dict[str, Any] | None:
        return self._by("interpretation", "interpretation_id", interpretation_id)

    def save_interpretation(self, record: dict[str, Any]) -> dict[str, Any]:
        return self._save("interpretation", record)

    def save_routing_decision(self, record: dict[str, Any]) -> dict[str, Any]:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 87))", (f"routing:{record['fingerprint']}",))
            cursor.execute("SELECT * FROM oc_scientific_interpretation.routing_decisions WHERE fingerprint=%s", (record["fingerprint"],))
            existing = cursor.fetchone()
            if existing:
                return self._record(existing)  # type: ignore[return-value]
            cursor.execute(
                "INSERT INTO oc_scientific_interpretation.routing_decisions(interpretation_id,policy_name,policy_version,path,fingerprint,payload) VALUES(%s,%s,%s,%s,%s,%s) RETURNING *",
                (record["interpretation_id"], record["policy_name"], record["policy_version"], record["path"], record["fingerprint"], Jsonb(record)),
            )
            return self._record(cursor.fetchone())  # type: ignore[return-value]

    def routing_by_fingerprint(self, fingerprint: str) -> dict[str, Any] | None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT * FROM oc_scientific_interpretation.routing_decisions WHERE fingerprint=%s", (fingerprint,))
            return self._record(cursor.fetchone())

    def routing_decision(self, routing_decision_id: int) -> dict[str, Any] | None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT * FROM oc_scientific_interpretation.routing_decisions WHERE routing_decision_id=%s", (routing_decision_id,))
            return self._record(cursor.fetchone())

    def assertion_by_fingerprint(self, fingerprint: str) -> dict[str, Any] | None:
        return self._by("assertion", "fingerprint", fingerprint)

    def save_assertion(self, record: dict[str, Any]) -> dict[str, Any]:
        return self._save("assertion", record)

    def save_correction(self, record: dict[str, Any]) -> dict[str, Any]:
        payload = dict(record)
        payload["fingerprint"] = None
        return self._save("correction", payload)

    def audit(self, event_type: str, artifact_type: str, artifact_id: int, details: dict[str, Any], actor: str = "system") -> None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO oc_scientific_interpretation.audit_events(event_type,artifact_type,artifact_id,actor,details) VALUES(%s,%s,%s,%s,%s)",
                (event_type, artifact_type, artifact_id, actor, Jsonb(details)),
            )

    def history(self, artifact_type: str, artifact_id: int) -> list[dict[str, Any]]:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT * FROM oc_scientific_interpretation.audit_events WHERE artifact_type=%s AND artifact_id=%s ORDER BY event_id", (artifact_type, artifact_id))
            return [dict(row) for row in cursor.fetchall()]
