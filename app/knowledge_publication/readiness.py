from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from time import perf_counter
import psycopg
from psycopg.rows import dict_row


class ReadinessSeverity(StrEnum):
    CRITICAL = "CRITICAL"
    ERROR = "ERROR"


@dataclass(frozen=True)
class ReadinessFinding:
    component: str
    reason: str
    severity: ReadinessSeverity
    recommended_action: str
    count: int


@dataclass(frozen=True)
class OperationalReadinessReport:
    healthy: bool
    counts: dict[str, int]
    provenance_coverage: float
    projection_statistics: dict[str, int]
    latency_ms: dict[str, float]
    duplicate_suppression_counts: dict[str, int]
    findings: tuple[ReadinessFinding, ...]


class PostgresPublicationReadinessRepository:
    """Read-only, fail-closed validation of the governed publication system."""

    REQUIRED_TABLES = (
        "policy_versions",
        "policy_lifecycle_events",
        "publication_candidates",
        "lifecycle_transitions",
        "authorization_decisions",
        "audit_events",
        "graph_change_sets",
        "graph_transaction_manifests",
        "graph_versions",
        "current_graph_version",
        "graph_object_versions",
        "graph_provenance_links",
        "graph_transaction_attempts",
        "publication_lineage",
        "publication_lifecycle_actions",
        "publication_projection_events",
        "reevaluation_records",
        "publication_dependencies",
        "propagation_checkpoints",
        "downstream_impacts",
        "rollback_manifests",
        "rollback_transactions",
    )

    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("DATABASE_URL_REQUIRED")
        self.database_url = database_url

    def _connect(self):
        return psycopg.connect(
            self.database_url, row_factory=dict_row, connect_timeout=10
        )

    @staticmethod
    def _finding(
        findings: list[ReadinessFinding],
        component: str,
        reason: str,
        count: int,
        action: str,
        severity: ReadinessSeverity = ReadinessSeverity.ERROR,
    ) -> None:
        if count:
            findings.append(
                ReadinessFinding(component, reason, severity, action, count)
            )

    def validate(self) -> OperationalReadinessReport:
        findings: list[ReadinessFinding] = []
        counts: dict[str, int] = {}
        projections: dict[str, int] = {}
        latency: dict[str, float] = {}
        suppressed: dict[str, int] = {}
        try:
            with self._connect() as con:
                con.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                with con.cursor() as cur:
                    self._validate_schema(cur, findings)
                    self._collect_counts(cur, counts, projections, suppressed)
                    self._validate_registries(cur, findings)
                    self._validate_graph(cur, findings)
                    self._validate_provenance(cur, findings)
                    self._validate_lifecycle(cur, findings)
                    self._validate_rollback(cur, findings)
                    self._validate_audit(cur, findings)
                    self._measure(cur, latency)
                    objects = counts["graph_objects"]
                    covered = counts["provenance_covered_objects"]
                    coverage = 1.0 if objects == 0 else covered / objects
        except ReadinessValidationError:
            raise
        except Exception as exc:
            raise ReadinessValidationError(
                "READINESS_VALIDATION_UNAVAILABLE", str(exc)
            ) from exc
        return OperationalReadinessReport(
            healthy=not findings,
            counts=counts,
            provenance_coverage=coverage,
            projection_statistics=projections,
            latency_ms=latency,
            duplicate_suppression_counts=suppressed,
            findings=tuple(findings),
        )

    def require_healthy(self) -> OperationalReadinessReport:
        report = self.validate()
        if not report.healthy:
            reasons = ",".join(
                f"{item.component}:{item.reason}:{item.count}"
                for item in report.findings
            )
            raise ReadinessValidationError("PUBLICATION_SYSTEM_NOT_READY", reasons)
        return report

    def _validate_schema(self, cur, findings: list[ReadinessFinding]) -> None:
        cur.execute(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='oc_knowledge_publication' AND c.relkind IN('r','p')"
        )
        present = {row["relname"] for row in cur.fetchall()}
        missing = sorted(set(self.REQUIRED_TABLES) - present)
        self._finding(
            findings,
            "migration_state",
            "REQUIRED_TABLE_MISSING",
            len(missing),
            "Apply the missing additive BUILD-088 migrations in order.",
            ReadinessSeverity.CRITICAL,
        )
        cur.execute(
            "SELECT count(*) AS n FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
            "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='oc_knowledge_publication' "
            "AND NOT t.tgisinternal AND t.tgname LIKE 'protect_088%'"
        )
        protected = cur.fetchone()["n"]
        self._finding(
            findings,
            "constraints",
            "IMMUTABILITY_TRIGGER_MISSING",
            max(0, 21 - protected),
            "Restore the additive append-only protection triggers.",
            ReadinessSeverity.CRITICAL,
        )
        cur.execute(
            "SELECT count(*) AS n FROM pg_indexes WHERE schemaname='oc_knowledge_publication'"
        )
        self._finding(
            findings,
            "indexes",
            "REQUIRED_INDEX_SET_INCOMPLETE",
            int(cur.fetchone()["n"] < 30),
            "Apply BUILD-088B through BUILD-088D migrations and inspect index state.",
        )

    @staticmethod
    def _scalar(cur, query: str) -> int:
        cur.execute(query)
        return int(cur.fetchone()["n"])

    def _collect_counts(self, cur, counts, projections, suppressed) -> None:
        tables = {
            "publications": "publication_candidates",
            "policies": "policy_versions",
            "graph_versions": "graph_versions",
            "graph_objects": "graph_object_versions",
            "rollback_events": "rollback_transactions",
            "reevaluation_events": "reevaluation_records",
        }
        for key, table in tables.items():
            counts[key] = self._scalar(
                cur, f"SELECT count(*) AS n FROM oc_knowledge_publication.{table}"
            )
        counts["provenance_covered_objects"] = self._scalar(
            cur,
            "SELECT count(DISTINCT object_version_id) AS n FROM oc_knowledge_publication.graph_provenance_links",
        )
        cur.execute(
            "SELECT state,count(*) AS n FROM (SELECT DISTINCT ON(publication_id) publication_id,state "
            "FROM oc_knowledge_publication.lifecycle_transitions ORDER BY publication_id,transition_id DESC) s GROUP BY state"
        )
        states = {row["state"].lower(): int(row["n"]) for row in cur.fetchall()}
        for state in ("published", "withdrawn", "retracted", "superseded"):
            counts[f"{state}_publications"] = states.get(state, 0)
        cur.execute(
            "SELECT projection,count(*) AS n FROM oc_knowledge_publication.current_publication_projection GROUP BY projection"
        )
        projections.update({row["projection"]: int(row["n"]) for row in cur.fetchall()})
        suppressed["publication_idempotency"] = self._scalar(
            cur,
            "SELECT count(*) AS n FROM oc_knowledge_publication.graph_transaction_attempts WHERE outcome='NO_OP_DUPLICATE'",
        )
        suppressed["lifecycle_idempotency"] = self._scalar(
            cur,
            "SELECT count(*) AS n FROM oc_knowledge_publication.audit_events WHERE event_type LIKE '%DUPLICATE%'",
        )

    def _validate_registries(self, cur, findings) -> None:
        checks = (
            ("policy_registry", "MULTIPLE_ACTIVE_POLICY_VERSIONS", """
             SELECT count(*) AS n FROM (SELECT p.policy_id FROM oc_knowledge_publication.policy_versions p
             JOIN LATERAL (SELECT state FROM oc_knowledge_publication.policy_lifecycle_events e
             WHERE e.policy_version_id=p.policy_version_id ORDER BY policy_event_id DESC LIMIT 1) s ON true
             WHERE s.state='ACTIVE' GROUP BY p.policy_id HAVING count(*)>1) x""",
             "Retire all but one active immutable policy version."),
            ("publication_registry", "DUPLICATE_PUBLICATION_FINGERPRINT", "SELECT count(*) AS n FROM (SELECT fingerprint FROM oc_knowledge_publication.publication_candidates GROUP BY fingerprint HAVING count(*)>1) x", "Remove the bypass and investigate the violated unique constraint without rewriting history."),
            ("publication_registry", "AUTHORIZED_DECISION_ORPHAN", "SELECT count(*) AS n FROM oc_knowledge_publication.authorization_decisions d LEFT JOIN oc_knowledge_publication.publication_candidates p ON p.publication_id=d.publication_id WHERE p.publication_id IS NULL", "Restore registry referential integrity from the immutable source records."),
        )
        for component, reason, query, action in checks:
            self._finding(findings, component, reason, self._scalar(cur, query), action)

    def _validate_graph(self, cur, findings) -> None:
        checks = (
            ("graph_version_lineage", "NON_CONTIGUOUS_SEQUENCE", "SELECT count(*) AS n FROM (SELECT sequence,lag(sequence) OVER(ORDER BY sequence) prior FROM oc_knowledge_publication.graph_versions) x WHERE prior IS NOT NULL AND sequence<>prior+1", "Investigate the missing or duplicate atomic graph commit."),
            ("graph_version_lineage", "BROKEN_PARENT_CHAIN", "SELECT count(*) AS n FROM oc_knowledge_publication.graph_versions child LEFT JOIN oc_knowledge_publication.graph_versions parent ON parent.graph_version_id=child.parent_graph_version_id WHERE child.sequence>1 AND (parent.graph_version_id IS NULL OR parent.sequence<>child.sequence-1)", "Restore lineage consistency through a governed corrective transaction."),
            ("graph_projection", "CURRENT_POINTER_INVALID", "SELECT count(*) AS n FROM oc_knowledge_publication.current_graph_version c LEFT JOIN oc_knowledge_publication.graph_versions g ON g.graph_version_id=c.graph_version_id WHERE c.sequence<>COALESCE(g.sequence,0)", "Block publication and repair the current pointer through controlled recovery."),
            ("graph_transactions", "GRAPH_VERSION_WITHOUT_TRANSACTION", "SELECT count(*) AS n FROM oc_knowledge_publication.graph_versions g LEFT JOIN oc_knowledge_publication.graph_transaction_manifests m ON m.graph_transaction_id=g.graph_transaction_id WHERE m.graph_transaction_id IS NULL", "Investigate atomic transaction history corruption."),
            ("graph_objects", "DUPLICATE_GRAPH_OBJECT_VERSION", "SELECT count(*) AS n FROM (SELECT object_key,object_version FROM oc_knowledge_publication.graph_object_versions GROUP BY object_key,object_version HAVING count(*)>1) x", "Block writes and investigate the violated object-version identity constraint."),
        )
        for component, reason, query, action in checks:
            self._finding(findings, component, reason, self._scalar(cur, query), action)

    def _validate_provenance(self, cur, findings) -> None:
        missing_links = self._scalar(
            cur,
            "SELECT count(*) AS n FROM oc_knowledge_publication.graph_object_versions o WHERE NOT EXISTS "
            "(SELECT 1 FROM oc_knowledge_publication.graph_provenance_links p WHERE p.object_version_id=o.object_version_id)",
        )
        self._finding(findings, "provenance", "GRAPH_OBJECT_PROVENANCE_MISSING", missing_links, "Quarantine the affected projection and reconstruct links from the immutable transaction snapshot.", ReadinessSeverity.CRITICAL)
        incomplete = self._scalar(
            cur,
            "SELECT count(*) AS n FROM oc_knowledge_publication.graph_provenance_links p "
            "LEFT JOIN oc_knowledge_publication.publication_candidates c ON c.publication_id=p.publication_id "
            "LEFT JOIN oc_scientific_interpretation.canonical_assertions a ON a.assertion_id=p.assertion_id "
            "WHERE c.publication_id IS NULL OR a.assertion_id IS NULL OR p.source_revision_id IS NULL "
            "OR jsonb_array_length(COALESCE(c.trusted_snapshot->'assertion'->'supporting_interpretation_ids','[]'::jsonb))=0 "
            "OR jsonb_array_length(COALESCE(c.trusted_snapshot->'provenance_roots','[]'::jsonb))=0",
        )
        self._finding(findings, "provenance", "INCOMPLETE_EVIDENCE_TRAVERSAL", incomplete, "Block serving and restore the exact assertion, interpretation, packet, and source-revision references.", ReadinessSeverity.CRITICAL)

    def _validate_lifecycle(self, cur, findings) -> None:
        allowed = {
            None: {"PUBLICATION_CANDIDATE"},
            "PUBLICATION_CANDIDATE": {"VALIDATING"},
            "VALIDATING": {"AUTHORIZED", "REJECTED"},
            "AUTHORIZED": {"TRANSACTION_PREPARED", "PUBLICATION_FAILED"},
            "TRANSACTION_PREPARED": {"PUBLISHING", "PUBLICATION_FAILED"},
            "PUBLISHING": {"PUBLISHED", "PUBLICATION_FAILED", "ROLLBACK_REQUIRED"},
            "PUBLICATION_FAILED": {"VALIDATING", "REJECTED", "ROLLBACK_REQUIRED"},
            "PUBLISHED": {"REEVALUATION_REQUIRED", "SUPERSEDED", "WITHDRAWN", "RETRACTED", "ROLLBACK_REQUIRED"},
            "REEVALUATION_REQUIRED": {"VALIDATING", "SUPERSEDED", "WITHDRAWN", "RETRACTED"},
            "WITHDRAWN": {"PUBLISHED"},
            "ROLLBACK_REQUIRED": {"ROLLED_BACK", "PUBLICATION_FAILED"},
        }
        cur.execute("SELECT publication_id,state FROM oc_knowledge_publication.lifecycle_transitions ORDER BY publication_id,transition_id")
        previous: dict[int, str] = {}
        invalid = 0
        for row in cur.fetchall():
            prior = previous.get(row["publication_id"])
            if row["state"] not in allowed.get(prior, set()):
                invalid += 1
            previous[row["publication_id"]] = row["state"]
        self._finding(findings, "lifecycle", "INVALID_LIFECYCLE_HISTORY", invalid, "Quarantine the publication and investigate the lifecycle-writer bypass.", ReadinessSeverity.CRITICAL)
        broken_lineage = self._scalar(cur, "SELECT count(*) AS n FROM oc_knowledge_publication.publication_lineage l LEFT JOIN oc_knowledge_publication.publication_candidates p ON p.publication_id=l.predecessor_publication_id LEFT JOIN oc_knowledge_publication.publication_candidates s ON s.publication_id=l.successor_publication_id WHERE p.publication_id IS NULL OR s.publication_id IS NULL OR l.prior_assertion_version>=l.successor_assertion_version")
        self._finding(findings, "publication_lineage", "BROKEN_SUPERSESSION_LINEAGE", broken_lineage, "Reevaluate the affected publication lineage using immutable assertion versions.")
        missing_projection = self._scalar(cur, "SELECT count(*) AS n FROM (SELECT DISTINCT ON(publication_id) publication_id,state FROM oc_knowledge_publication.lifecycle_transitions ORDER BY publication_id,transition_id DESC) s WHERE state IN('PUBLISHED','WITHDRAWN','RETRACTED','SUPERSEDED','ROLLED_BACK') AND NOT EXISTS (SELECT 1 FROM oc_knowledge_publication.current_publication_projection p WHERE p.publication_id=s.publication_id)")
        self._finding(findings, "projections", "TERMINAL_PUBLICATION_PROJECTION_MISSING", missing_projection, "Rebuild only the missing projection event through governed recovery.")

    def _validate_rollback(self, cur, findings) -> None:
        invalid = self._scalar(cur, "SELECT count(*) AS n FROM oc_knowledge_publication.rollback_transactions t JOIN oc_knowledge_publication.rollback_manifests m USING(rollback_id) LEFT JOIN oc_knowledge_publication.graph_versions g ON g.graph_version_id=m.failed_graph_version_id WHERE g.graph_version_id IS NULL OR t.original_graph_transaction_id<>m.original_graph_transaction_id OR t.restored_graph_version_id IS DISTINCT FROM m.coherent_graph_version_id")
        self._finding(findings, "rollback", "ROLLBACK_HISTORY_INCOHERENT", invalid, "Block publication and investigate the immutable rollback manifest and transaction.", ReadinessSeverity.CRITICAL)

    def _validate_audit(self, cur, findings) -> None:
        missing = self._scalar(cur, "SELECT count(*) AS n FROM oc_knowledge_publication.graph_versions g WHERE NOT EXISTS (SELECT 1 FROM oc_knowledge_publication.audit_events a WHERE a.artifact_id=g.graph_transaction_id AND a.event_type='GRAPH_TRANSACTION_COMMITTED')")
        self._finding(findings, "audit", "PUBLICATION_AUDIT_MISSING", missing, "Quarantine the affected graph version; audit failure invalidates the transition.", ReadinessSeverity.CRITICAL)
        lifecycle_missing = self._scalar(cur, "SELECT count(*) AS n FROM oc_knowledge_publication.publication_lifecycle_actions a WHERE NOT EXISTS (SELECT 1 FROM oc_knowledge_publication.audit_events e WHERE e.artifact_id=a.publication_id AND e.created_at>=a.created_at)")
        self._finding(findings, "audit", "LIFECYCLE_AUDIT_MISSING", lifecycle_missing, "Investigate the atomic lifecycle/audit boundary.")

    @staticmethod
    def _timed(cur, query: str) -> float:
        started = perf_counter()
        cur.execute(query)
        cur.fetchall()
        return round((perf_counter() - started) * 1000, 3)

    def _measure(self, cur, latency) -> None:
        queries: dict[str, str] = {
            "publication_lookup": "SELECT publication_id FROM oc_knowledge_publication.publication_candidates ORDER BY publication_id DESC LIMIT 1",
            "duplicate_lookup": "SELECT fingerprint FROM oc_knowledge_publication.publication_candidates ORDER BY publication_id DESC LIMIT 1",
            "graph_version_lookup": "SELECT graph_version_id FROM oc_knowledge_publication.current_graph_version WHERE singleton",
            "current_projection_lookup": "SELECT * FROM oc_knowledge_publication.authoritative_current_publications LIMIT 100",
            "lineage_traversal": "SELECT * FROM oc_knowledge_publication.publication_lineage ORDER BY lineage_id LIMIT 100",
            "historical_reconstruction": "SELECT * FROM oc_knowledge_publication.graph_object_versions ORDER BY graph_version_id,object_version_id LIMIT 1000",
            "provenance_traversal": "SELECT * FROM oc_knowledge_publication.graph_provenance_links ORDER BY provenance_link_id LIMIT 1000",
            "rollback_lookup": "SELECT * FROM oc_knowledge_publication.rollback_transactions ORDER BY rollback_transaction_id DESC LIMIT 100",
        }
        latency.update({name: self._timed(cur, query) for name, query in queries.items()})


class ReadinessValidationError(RuntimeError):
    def __init__(self, reason_code: str, detail: str) -> None:
        super().__init__(f"{reason_code}: {detail}")
        self.reason_code = reason_code
        self.detail = detail
