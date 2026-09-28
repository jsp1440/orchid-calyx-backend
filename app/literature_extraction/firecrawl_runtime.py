"""Render composition for one already admitted canonical GitHub acquisition lease.

This module neither schedules nor claims work. All scientific writes use existing
source/import/intelligence/candidate/aggregate repositories; completion stays in
Swarm. External transports are the only replaceable test boundary.
"""

from __future__ import annotations

import json
import os
import re
from hashlib import sha256

import psycopg
from psycopg.rows import dict_row
from pydantic import BaseModel, ConfigDict, Field

from app.calyx_engineering.github import GitHubEngineeringClient
from app.candidate_knowledge.postgres_repository import PostgresCandidateRepository
from app.candidate_knowledge.service import CandidateExtractionService
from app.evidence_aggregation.postgres_repository import PostgresAggregateRepository
from app.evidence_aggregation.service import EvidenceAggregationService
from runtime.research_station_store import PostgresProjectRecordStore
from runtime.swarm import GovernorPolicy, SwarmExecutionGovernor

from .candidate_handoff import LiteratureCandidateHandoffService
from .canonical_binding_resolver import (
    BindingScope,
    PostgresLiteratureSourceBindingRepository,
)
from .firecrawl_acquisition import (
    acquire_for_swarm_issue,
    verify_swarm_acquisition_lease,
)
from .firecrawl_provider import (
    AcquisitionBlocked,
    FirecrawlConfig,
    FirecrawlProvider,
    PostgresFirecrawlReservation,
)
from .firecrawl_registration import PostgresFirecrawlRegistration
from .repository import LiteratureResultRepository

CANONICAL_REPOSITORY = "jsp1440/orchid-calyx-backend"
SCOPE = BindingScope("oc-autonomy", "firecrawl")


class AcquisitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repository: str = CANONICAL_REPOSITORY
    issue_number: int = Field(gt=0)
    run_id: int = Field(gt=0)
    run_attempt: int = Field(gt=0)
    comment_id: int = Field(gt=0)


def connection():
    url = os.getenv("DATABASE_URL") or os.getenv("TEST_DATABASE_URL")
    if not url:
        raise AcquisitionBlocked("ACQUISITION_DATABASE_REQUIRED")
    return psycopg.connect(url, connect_timeout=10)


def _record_store():
    def execute(operation):
        with connection() as conn, conn.cursor(row_factory=dict_row) as cursor:
            return operation(cursor)

    return PostgresProjectRecordStore(execute)


def _governor(config):
    # Reuse the existing governor; durable provider reservations independently
    # enforce the daily ceiling across processes/restarts, without refilling it.
    task_cap = (
        config.max_call_cost
        * (config.max_searches + config.max_documents)
        * (config.retry_cap + 1)
    )
    return SwarmExecutionGovernor(
        GovernorPolicy(
            paid_execution_enabled=not config.dry_run,
            paid_worker_concurrency=1,
            max_retries=config.retry_cap,
            per_run_budget=task_cap,
            daily_budget=config.daily_budget,
            monthly_budget=config.daily_budget,
            provider_allowlist=frozenset({"firecrawl"}),
        ),
        no_api_mode_raw=os.getenv("NO_API_MODE", "true"),
    )


def validate_persisted_acquisition(result, literature_repository):
    """Technical integrity validation; never scientific approval/publication."""
    if (
        result.get("status") != "review_pending"
        or result.get("published") is not False
        or not result.get("sources")
    ):
        raise AcquisitionBlocked("ACQUISITION_RESULT_INVALID")
    url = os.getenv("DATABASE_URL") or os.getenv("TEST_DATABASE_URL")
    candidates = PostgresCandidateRepository(url)
    aggregates = PostgresAggregateRepository(url)
    for source in result["sources"]:
        paper = literature_repository.get(source["paper_id"])
        if paper is None or paper.source.content_hash != source["source_hash"]:
            raise AcquisitionBlocked("PERSISTED_LITERATURE_MISSING")
        with connection() as conn, conn.cursor() as cursor:
            binding = PostgresLiteratureSourceBindingRepository().get(
                cursor,
                scope=SCOPE,
                paper_id=source["paper_id"],
                analysis_id=source["analysis_id"],
            )
            if (
                binding is None
                or binding.binding.fingerprint != source["binding_fingerprint"]
            ):
                raise AcquisitionBlocked("PERSISTED_BINDING_MISMATCH")
            cursor.execute(
                "SELECT content_bytes,registry_id FROM oc_import.document_revisions WHERE revision_id=%s",
                (source["revision_id"],),
            )
            row = cursor.fetchone()
            if row is None:
                raise AcquisitionBlocked("PERSISTED_SOURCE_MISSING")
            if source.get("source_registration_id", row[1]) != row[1]:
                raise AcquisitionBlocked("PERSISTED_SOURCE_IDENTITY_MISMATCH")
            source["source_registration_id"] = row[1]
            binding.binding.validate_integrity(paper, bytes(row[0]))
        ids = set(source["candidate_ids"])
        persisted = [
            candidate
            for candidate in candidates.candidates
            if candidate["candidate_id"] in ids
        ]
        if (
            not ids
            or len(persisted) != len(ids)
            or any(c["published"] or c["review_state"] != "REQUIRED" for c in persisted)
        ):
            raise AcquisitionBlocked("PERSISTED_CANDIDATE_VALIDATION_FAILED")
        run = aggregates.runs.get(source["aggregate_run_id"])
        if not run or run["state"] != "COMPLETED":
            raise AcquisitionBlocked("PERSISTED_AGGREGATION_INCOMPLETE")
        members = {
            c.candidate_id
            for item in aggregates.items[source["aggregate_run_id"]]
            for c in item["candidates"]
        }
        if not ids.issubset(members):
            raise AcquisitionBlocked("AGGREGATE_PROVENANCE_INCOMPLETE")
    return {
        "status": "passed",
        "scope": "persistent-source-and-candidate-integrity",
        "scientific_review_required": True,
    }


async def execute_acquisition(
    request: AcquisitionRequest, *, github=None, fixture_transport=None
):
    """Execute a verified lease once; safe replay uses its durable receipt."""
    github = github or GitHubEngineeringClient(CANONICAL_REPOSITORY)
    lease = request.model_dump()
    lease["read_issue"] = lambda number: github._request("GET", f"/issues/{number}")
    lease["read_lease"] = lambda number: github._request(
        "GET", f"/issues/comments/{number}"
    )
    issue = verify_swarm_acquisition_lease(**lease)
    genera = re.findall(
        r"^OC-ACQUISITION-GENUS:\s*([A-Z][a-z]+)\s*$",
        issue.get("body", ""),
        re.MULTILINE,
    )
    if len(genera) != 1:
        raise AcquisitionBlocked("CANONICAL_ACQUISITION_GENUS_REQUIRED")
    config = FirecrawlConfig.from_env()
    if config.pilot_mode and genera[0] != os.getenv(
        "FIRECRAWL_PILOT_GENUS", "Paphiopedilum"
    ):
        raise AcquisitionBlocked("OUTSIDE_ACQUISITION_PILOT")
    reservation = PostgresFirecrawlReservation(connection)
    if (
        config.pilot_mode
        and not config.dry_run
        and str(request.issue_number) != os.getenv("FIRECRAWL_PILOT_ISSUE_NUMBER", "")
    ):
        raise AcquisitionBlocked("LIVE_PILOT_ISSUE_SCOPE_REQUIRED")
    provider = FirecrawlProvider(
        config,
        governor=_governor(config),
        reserve=reservation,
        reserve_credits=reservation.reserve_credits,
        observe_credits=reservation.observe_credits,
        fixture_transport=fixture_transport,
    )
    provider.lease_check = lambda: verify_swarm_acquisition_lease(**lease)
    provider._gate()
    identity = request.model_dump()
    key = {
        "owner_key": SCOPE.owner_id,
        "project_id": SCOPE.project_id,
        "kind": "artifact",
        "record_id": f"acquisition:{request.issue_number}:{request.comment_id}",
    }
    literature = LiteratureResultRepository(
        os.getenv("LITERATURE_EXTRACTION_ROOT", "runtime/literature_extraction")
    )
    # Existing PostgreSQL advisory locking fences duplicate backend deliveries;
    # the canonical GitHub lease remains the only admission/ownership authority.
    lock_id = int.from_bytes(
        sha256(f"firecrawl:{request.issue_number}".encode()).digest()[:8],
        "big",
        signed=True,
    )
    with connection() as lock_conn, lock_conn.cursor() as lock_cursor:
        lock_cursor.execute("SELECT pg_try_advisory_xact_lock(%s)", (lock_id,))
        if not lock_cursor.fetchone()[0]:
            raise AcquisitionBlocked("ACQUISITION_ALREADY_EXECUTING")
        store = _record_store()
        prior = store.get(**key)
        if prior is not None:
            if any(prior.get(k) != v for k, v in identity.items()):
                raise AcquisitionBlocked("ACQUISITION_RECEIPT_IDENTITY_MISMATCH")
            prior["validation"] = validate_persisted_acquisition(prior, literature)
            verify_swarm_acquisition_lease(**lease)
            return prior
        from runtime.knowledge_graph.firecrawl_taxonomy import (
            load_persistent_canonical_registry,
        )

        taxonomy = load_persistent_canonical_registry(connection)
        target_markers = re.findall(
            r"^OC-ACQUISITION-TARGETS:\s*(\[[^\n]*\])\s*$",
            issue.get("body", ""),
            re.MULTILINE,
        )
        if len(target_markers) > 1:
            raise AcquisitionBlocked("AMBIGUOUS_TARGETED_GAP")
        targets = json.loads(target_markers[0]) if target_markers else []
        if not isinstance(targets, list) or len(targets) > 5:
            raise AcquisitionBlocked("INVALID_TARGETED_GAP")
        for name in targets:
            if not isinstance(name, str):
                raise AcquisitionBlocked("INVALID_TARGETED_GAP")
            taxon = taxonomy.resolve(name)
            if (
                taxon is None
                or taxon.status != "accepted"
                or taxon.canonical_name != name
                or not name.startswith(genera[0] + " ")
            ):
                raise AcquisitionBlocked("UNBOUND_TARGETED_GAP")
        database_url = os.getenv("DATABASE_URL") or os.getenv("TEST_DATABASE_URL")
        candidate_repository = PostgresCandidateRepository(database_url)
        aggregate_repository = PostgresAggregateRepository(database_url)
        result = await acquire_for_swarm_issue(
            **lease,
            provider=provider,
            genus=genera[0],
            target_names=targets,
            taxonomy=taxonomy,
            literature_repository=literature,
            register_and_bind=PostgresFirecrawlRegistration(connection, scope=SCOPE),
            handoff_service=LiteratureCandidateHandoffService(
                CandidateExtractionService(candidate_repository), candidate_repository
            ),
            aggregation_service=EvidenceAggregationService(aggregate_repository),
        )
        result.update(identity)
        result["firecrawl_credits"] = provider.credit_receipt()
        result["validation"] = validate_persisted_acquisition(result, literature)
        verify_swarm_acquisition_lease(**lease)
        store.put(**key, record=result)
        return result
