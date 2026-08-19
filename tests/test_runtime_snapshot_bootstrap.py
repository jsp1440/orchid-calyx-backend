from app.persistence.state_repository import PostgresStateMixin


class FakeCursor:
    def __init__(self, *, relation=None):
        self.relation = relation
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, statement, params=None):
        self.statements.append((str(statement), params))

    def fetchone(self):
        return {"relation": self.relation}


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.commits += 1


class ProbeRepository(PostgresStateMixin):
    snapshot_kind = "semantic_index"
    lock_id = 1
    state_attributes = ()

    def __init__(self, connection):
        self.connection = connection
        self.database_url = "postgresql://example.invalid/test"

    def _connect(self):
        return self.connection


def test_bootstrap_creates_additive_runtime_store_when_missing():
    cursor = FakeCursor(relation=None)
    conn = FakeConnection(cursor)
    repo = ProbeRepository(conn)

    repo._bootstrap_runtime_snapshot_storage_if_missing()

    sql = "\n".join(statement for statement, _ in cursor.statements)
    assert "CREATE SCHEMA IF NOT EXISTS oc_candidate_knowledge" in sql
    assert "CREATE TABLE IF NOT EXISTS oc_candidate_knowledge.runtime_repository_snapshots" in sql
    assert "'semantic_index'" in sql
    assert "CREATE TABLE IF NOT EXISTS oc_candidate_knowledge.runtime_repository_audit" in sql
    assert "runtime_repository_snapshot_audit" in sql
    assert conn.commits == 1


def test_bootstrap_does_not_rewrite_existing_runtime_store():
    cursor = FakeCursor(relation="oc_candidate_knowledge.runtime_repository_snapshots")
    conn = FakeConnection(cursor)
    repo = ProbeRepository(conn)

    repo._bootstrap_runtime_snapshot_storage_if_missing()

    assert len(cursor.statements) == 1
    assert "to_regclass" in cursor.statements[0][0]
    assert conn.commits == 0
