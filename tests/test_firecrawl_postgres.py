"""Production canonical lifecycle against disposable PostgreSQL.

Only GitHub and Firecrawl external transports are simulated. Taxonomy rows are
synthetic accepted-release fixtures, not evidence of production activation.
"""

from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path

import psycopg
import pytest

pytestmark = pytest.mark.requires_postgres
REPOSITORY = "jsp1440/orchid-calyx-backend"
URL = "https://flora.example/monograph"
TEXT = (
    "Synthetic morphology source; not published scientific measurements.\n\n"
    "Paphiopedilum delenatii leaf length 10-12 cm.\n"
    "Paphiopedilum delenatii leaf length 15 cm.\n"
    "Paphiopedilum armeniacum petal width 3 cm.\n"
)


class GitHubTransport:
    """External API responses only; all work/lease decisions remain production code."""

    def __init__(self):
        self.issues = {}
        self.comments = {}
        self.calls = []

    def __call__(self, args, payload=None):
        self.calls.append((deepcopy(args), deepcopy(payload)))
        if args[:2] == ["api", "graphql"]:
            nodes = list(deepcopy(self.issues).values())
            return {
                "data": {
                    "repository": {
                        "issues": {
                            "nodes": nodes,
                            "totalCount": len(nodes),
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                        }
                    }
                }
            }
        if args[0] == "api" and "GET" in args:
            endpoint = next(value for value in args if "/issues/comments/" in value)
            return deepcopy(self.comments[int(endpoint.rsplit("/", 1)[1])])
        if args[:2] == ["issue", "list"]:
            return list(deepcopy(self.issues).values())
        if args[:2] == ["label", "create"]:
            return None
        if args[:2] == ["issue", "create"]:
            number = len(self.issues) + 123
            labels = [args[i + 1] for i, value in enumerate(args) if value == "--label"]
            self.issues[number] = {
                "number": number,
                "title": args[args.index("--title") + 1],
                "body": args[args.index("--body") + 1],
                "state": "OPEN",
                "labels": [{"name": name} for name in labels],
                "stateReason": "",
            }
            return f"https://github.com/{REPOSITORY}/issues/{number}"
        if args[:2] == ["issue", "view"]:
            return deepcopy(self.issues[int(args[2])])
        if args[:2] == ["issue", "edit"]:
            issue = self.issues[int(args[2])]
            labels = {label["name"] for label in issue["labels"]}
            for index, arg in enumerate(args):
                if arg == "--remove-label":
                    labels.difference_update(args[index + 1].split(","))
                if arg == "--add-label":
                    labels.update(args[index + 1].split(","))
            issue["labels"] = [{"name": name} for name in sorted(labels)]
            return None
        if args[:2] == ["issue", "close"]:
            self.issues[int(args[2])].update(state="CLOSED", stateReason="COMPLETED")
            return None
        if args[:2] == ["issue", "comment"]:
            body = args[args.index("--body") + 1]
            number = int(args[2])
        elif args[0] == "api" and payload and "body" in payload:
            body = payload["body"]
            endpoint = next(value for value in args if "/issues/" in value)
            number = int(endpoint.split("/issues/")[1].split("/")[0])
        else:
            raise AssertionError(f"Unexpected GitHub transport operation: {args[:3]}")
        comment_id = len(self.comments) + 100
        receipt = {
            "id": comment_id,
            "body": body,
            "user": {"login": "github-actions[bot]"},
            "issue_url": f"https://api.github.com/repos/{REPOSITORY}/issues/{number}",
        }
        self.comments[comment_id] = receipt
        return deepcopy(receipt)


def firecrawl_transport(endpoint, payload):
    if endpoint == "search":
        assert "Paphiopedilum" in payload["query"]
        return 200, {
            "success": True,
            "data": {
                "web": [
                    {"url": URL},
                    {"url": URL + "#duplicate"},
                ]
            },
        }
    assert endpoint == "scrape" and payload["url"] == URL
    return 200, {
        "success": True,
        "data": {
            "markdown": TEXT,
            "metadata": {"sourceURL": URL},
        },
    }


@pytest.fixture
def database_url(monkeypatch):
    dsn = os.environ.get("TEST_DATABASE_URL") or os.environ["DATABASE_URL"]
    monkeypatch.setenv("DATABASE_URL", dsn)
    migrations = [
        "070_knowledge_intake.sql",
        "076a_universal_intake.sql",
        "079_controlled_mission_orchestration.sql",
        "081_brain_source_registry.sql",
        "082_controlled_drive_document_import.sql",
        "084_document_intelligence.sql",
        "116_literature_source_binding.sql",
        "CALYX-RECOVERY-001-research-station-records.sql",
    ]
    with psycopg.connect(dsn, autocommit=True) as conn:
        for filename in migrations:
            conn.execute(Path("migrations", filename).read_text())
        # These are the deployed canonical taxonomy table contracts. Their DDL
        # predates the migration set; the fixture does not activate a release.
        conn.execute("CREATE SCHEMA IF NOT EXISTS oc_source")
        conn.execute("""CREATE TABLE IF NOT EXISTS oc_source.source_snapshots (
            snapshot_id text PRIMARY KEY, source_system text,
            file_sha256 text, version_label text, row_count integer,
            acquired_at_utc text)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS oc_source.world_plants_load (
            snapshot_id text, name text, taxon_code text)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS public.orchid_taxonomy (
            id bigint PRIMARY KEY, scientific_name text, genus text)""")
        conn.execute(
            """INSERT INTO oc_source.source_snapshots VALUES
            ('firecrawl-fixture-release','world_plants',%s,'fixture',3,NULL)
            ON CONFLICT DO NOTHING""",
            ("a" * 64,),
        )
        for taxon_id, name in (
            (91001, "Paphiopedilum delenatii"),
            (91002, "Paphiopedilum armeniacum"),
            (91003, "Paphiopedilum rothschildianum"),
        ):
            conn.execute(
                """INSERT INTO public.orchid_taxonomy
                (id,scientific_name,genus) VALUES (%s,%s,'Paphiopedilum')
                ON CONFLICT DO NOTHING""",
                (taxon_id, name),
            )
            conn.execute(
                """INSERT INTO oc_source.world_plants_load
                (snapshot_id,name,taxon_code)
                VALUES ('firecrawl-fixture-release',%s,'S')""",
                (name,),
            )
    monkeypatch.setenv("FIRECRAWL_TAXONOMY_SNAPSHOT_ID", "firecrawl-fixture-release")
    return dsn


def test_postgres_canonical_vertical_slice(database_url, tmp_path, monkeypatch):
    import asyncio
    import json

    from app.calyx_engineering.github import GitHubEngineeringClient
    from app.candidate_knowledge.postgres_repository import PostgresCandidateRepository
    from app.evidence_aggregation.postgres_repository import PostgresAggregateRepository
    from app.literature_extraction.coverage_audit import (
        export_matrix_acquisition_coverage,
    )
    from app.literature_extraction.firecrawl_runtime import (
        AcquisitionRequest,
        execute_acquisition,
    )
    from runtime.knowledge_graph.firecrawl_taxonomy import (
        load_persistent_canonical_registry,
    )
    from scripts.oc_swarm_acquisition_worker import execute_claim
    from scripts.oc_swarm_claim import claim_workers
    from scripts.oc_swarm_controller import build_swarm_plan
    from scripts.oc_work_discovery import discover_matrix_coverage
    from scripts.oc_work_materialize import apply_plan, plan

    for name, value in {
        "FIRECRAWL_ENABLED": "true",
        "FIRECRAWL_DRY_RUN": "true",
        "FIRECRAWL_PILOT_MODE": "true",
        "FIRECRAWL_APPROVED_DOMAINS": "flora.example",
        "LITERATURE_EXTRACTION_ROOT": str(tmp_path / "literature"),
        "GITHUB_TOKEN": "synthetic-test-token",
        "FIRECRAWL_KILL_SWITCH": "false",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    connect = lambda: psycopg.connect(database_url)
    taxonomy = load_persistent_canonical_registry(connect)
    assert set(taxonomy.taxa) == {91001, 91002, 91003}
    aggregates = PostgresAggregateRepository(database_url)
    before = export_matrix_acquisition_coverage(taxonomy, aggregates)
    assert before["gaps"][0]["missing_taxon_ids"] == [91001, 91002, 91003]
    candidates = discover_matrix_coverage(before)
    report = {
        "schema": "oc.work-discovery.v1",
        "sources_evaluated": ["matrix-coverage"],
        "candidates": [candidate.to_record() for candidate in candidates],
    }
    materialization = plan(report, {}, search=lambda _: [])
    github = GitHubTransport()
    applied = apply_plan(materialization, REPOSITORY, dry_run=False, call=github)
    assert not applied["errors"]
    assert len(github.issues) == 1
    issue_number = next(iter(github.issues))
    assert {x["name"] for x in github.issues[issue_number]["labels"]} >= {"oc-queued"}
    snapshot = {"issues": list(deepcopy(github.issues).values())}
    admitted = build_swarm_plan(snapshot, worker_slots=1)
    assert admitted["acquisition_launch_count"] == 1
    assert admitted["provider_launch_count"] == 0
    claimed = claim_workers(
        admitted, snapshot, repository=REPOSITORY, run_id=77, call=github
    )
    assert claimed["launch_count"] == 1
    comment_id = claimed["confirmed"][0]["lease_comment_id"]
    assert {x["name"] for x in github.issues[issue_number]["labels"]} >= {"oc-running"}

    def github_http(_self, method, path, payload=None):
        assert method == "GET"
        if path.startswith("/issues/comments/"):
            return deepcopy(github.comments[int(path.rsplit("/", 1)[1])])
        return deepcopy(github.issues[int(path.rsplit("/", 1)[1])])

    monkeypatch.setattr(GitHubEngineeringClient, "_request", github_http)
    receipts = []

    def dispatch(identity):
        receipt = asyncio.run(
            execute_acquisition(
                AcquisitionRequest(**identity),
                fixture_transport=firecrawl_transport,
            )
        )

        def no_second_http(*_args):
            raise AssertionError("durable receipt replay must not reacquire")

        replay = asyncio.run(
            execute_acquisition(
                AcquisitionRequest(**identity),
                fixture_transport=no_second_http,
            )
        )
        assert replay == receipt
        receipts.append(receipt)
        return receipt

    identity = {
        "repository": REPOSITORY,
        "issue_number": issue_number,
        "run_id": 77,
        "run_attempt": 1,
        "comment_id": comment_id,
    }
    result = execute_claim(**identity, dispatch=dispatch, call=github)
    assert result["disposition"] == "done"
    assert result["replenishment_signal"] == "canonical-controller-refill"
    assert receipts[0]["validation"]["status"] == "passed"
    assert all(source["mocked"] for source in receipts[0]["sources"])
    assert {x["name"] for x in github.issues[issue_number]["labels"]} >= {"oc-done"}
    assert "oc-running" not in {
        x["name"] for x in github.issues[issue_number]["labels"]
    }

    # A fresh repository instance must recover the persisted artifacts.
    persisted = PostgresCandidateRepository(database_url)
    persisted_aggregates = PostgresAggregateRepository(database_url)
    assert len(persisted.candidates) == 3
    assert {candidate["normalized_subject"] for candidate in persisted.candidates} == {
        "local:orchid_taxonomy:91001",
        "local:orchid_taxonomy:91002",
    }
    assert all(not candidate["published"] for candidate in persisted.candidates)
    assert len(persisted.conflicts) >= 1
    serialized = json.dumps(persisted.candidates)
    assert "Paphiopedilum delenatii leaf length 10-12 cm." in serialized
    assert "Paphiopedilum delenatii leaf length 15 cm." in serialized
    assert "Paphiopedilum armeniacum" in serialized
    for aggregate in persisted_aggregates.aggregates:
        assert aggregate.get("measurements", {}).get("unweighted_mean") is None
    with connect() as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM oc_sources.document_inventory"
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute("SELECT count(*) FROM oc_import.hash_index").fetchone()[0] == 1
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM oc_document_intelligence.literature_source_bindings"
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM oc_document_intelligence.literature_evidence_bindings"
            ).fetchone()[0]
            == 3
        )
        (raw,) = conn.execute(
            "SELECT content_bytes FROM oc_import.document_revisions"
        ).fetchone()
        assert bytes(raw).decode() == TEXT
    after = export_matrix_acquisition_coverage(taxonomy, persisted_aggregates)
    assert after["covered_taxa"] == 2
    assert after["gaps"][0]["missing_taxon_ids"] == [91003]
    next_candidates = discover_matrix_coverage(after)
    assert next_candidates[0].fingerprint != candidates[0].fingerprint
    next_plan = plan(
        {**report, "candidates": [c.to_record() for c in next_candidates]},
        {},
        search=lambda _: [],
    )
    assert next_plan["actions"][0]["action"] == "create_issue"
    assert "oc-queued" in next_plan["actions"][0]["labels"]
