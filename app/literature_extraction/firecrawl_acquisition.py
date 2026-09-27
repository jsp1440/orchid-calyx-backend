"""Firecrawl capability composition over the existing literature/evidence services.

No queue or scientific store is owned here. The canonical worker supplies its
verified lease, source-registration/binding boundary, and persistent services.
Missing source identities block; this module never manufactures database IDs.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

from app.evidence_aggregation.models import CandidateInput
from app.literature_extraction.firecrawl_provider import AcquisitionBlocked
from app.parallel_platform.matrix_adapters import DimensionEvidence

from .candidate_handoff import LiteratureSourceBinding
from .context import PipelineConfig
from .extractors.metadata import MetadataExtractor
from .extractors.morphology import CanonicalMorphologyExtractor
from .ingest import WebSourceMetadata
from .registry import ExtractorRegistry
from .service import extract_and_persist


async def acquire_matrix_sources(
    *,
    provider,
    genus,
    task_id,
    taxonomy,
    literature_repository,
    register_and_bind,
    handoff_service,
    aggregation_service,
    verify_lease,
):
    """Acquire once per source, extracting multiple taxa without species crawls.

    ``register_and_bind`` must use canonical intake identities and return a
    CanonicalLiteratureSourceBinding with exact integrity. Production callers
    use the existing DocumentIntelligenceBindingResolver after source import.
    Service mutations must run within their repository's existing write scope.
    """
    verify_lease()
    provider.lease_check = verify_lease
    urls = provider.search(genus, task_id=task_id)
    if not urls:
        raise AcquisitionBlocked("NO_APPROVED_SOURCES")
    receipts = []
    for url in urls:
        verify_lease()
        source = provider.scrape(url, task_id=task_id)
        existing = literature_repository.get("paper-" + source.content_hash)
        if existing is not None and existing.source.origin_uri != source.url:
            raise AcquisitionBlocked("SOURCE_IDENTITY_COLLISION_REQUIRES_REVIEW")
        registry = ExtractorRegistry(
            [MetadataExtractor(), CanonicalMorphologyExtractor(taxonomy)]
        )
        release = taxonomy.canonical_release
        if release is None:
            raise AcquisitionBlocked("CANONICAL_TAXONOMY_RELEASE_REQUIRED")
        with TemporaryDirectory() as directory:
            path = Path(directory) / (source.content_hash + ".txt")
            path.write_bytes(source.markdown.encode())
            paper = await extract_and_persist(
                path,
                literature_repository,
                registry=registry,
                config=PipelineConfig(
                    extractor_settings={
                        "canonical_morphology": {
                            "taxonomy_snapshot": release.snapshot_id,
                            "taxonomy_hash": release.file_sha256,
                        }
                    }
                ),
                web_source=WebSourceMetadata(
                    origin_uri=source.url,
                    origin_content_hash=source.content_hash,
                    origin_media_type="text/markdown",
                    acquisition_method="firecrawl_v2_fixture"
                    if source.mocked
                    else "firecrawl_v2",
                ),
            )
        verify_lease()
        binding = register_and_bind(source, paper)
        binding.validate_integrity(paper, source.markdown.encode())
        payload = asdict(binding)
        payload.pop("paper_id")
        handoff = handoff_service.handoff(paper, LiteratureSourceBinding(**payload))
        if handoff["state"] != "COMPLETED" or not handoff["candidate_ids"]:
            raise AcquisitionBlocked("CANDIDATE_HANDOFF_INCOMPLETE")
        candidates = handoff_service.candidate_repository.candidates_for_run(
            handoff["candidate_run_id"]
        )
        inputs = []
        for candidate in candidates:
            links = [
                link
                for link in handoff_service.candidate_repository.evidence_links
                if link["candidate_id"] == candidate["candidate_id"]
            ]
            names = [
                e.name
                for e in paper.entities
                if any(
                    f"{identifier.scheme}:{identifier.value}"
                    == candidate["normalized_subject"]
                    for identifier in e.external_ids
                )
            ]
            inputs.append(
                CandidateInput(
                    candidate_id=candidate["candidate_id"],
                    candidate_version=candidate["version"],
                    candidate_type=candidate["kind"],
                    normalized_subject=candidate["normalized_subject"],
                    predicate=candidate["predicate"],
                    object_value=candidate["object_value"],
                    source_revision_id=binding.revision_id,
                    source_document_id=paper.paper_id,
                    source_anchor_ids=tuple(
                        link["anchor"]["anchor_id"] for link in links
                    ),
                    document_hash=source.content_hash,
                    source_lineage=source.url,
                    # Keep verbatim ranges in object_value; no numeric pooling.
                    taxon_links=tuple(
                        {
                            "candidate_taxon_id": candidate["normalized_subject"],
                            "source_name": name,
                            "confidence": 1.0,
                        }
                        for name in names
                    ),
                    metadata={
                        "source_name": names[0] if len(names) == 1 else None,
                        "source_names": names,
                        "provider": "firecrawl",
                        "taxonomy_snapshot": release.snapshot_id,
                    },
                    display_policy="METADATA_ONLY",
                )
            )
        verify_lease()
        plan = aggregation_service.preview(inputs)
        result = aggregation_service.execute(plan["aggregate_run_id"])
        if result["state"] != "COMPLETED":
            raise AcquisitionBlocked("AGGREGATION_INCOMPLETE")
        receipts.append(
            {
                "paper_id": paper.paper_id,
                "source_hash": source.content_hash,
                "binding_fingerprint": binding.fingerprint,
                "candidate_ids": handoff["candidate_ids"],
                "aggregate_run_id": plan["aggregate_run_id"],
                "mocked": source.mocked,
            }
        )
    return {
        "status": "review_pending",
        "sources": receipts,
        "published": False,
        "matrix_readiness": DimensionEvidence(
            dimension="morphology",
            availability="degraded",
            provenance=tuple(r["paper_id"] for r in receipts),
            limitations=(
                "Unreviewed acquired claims; scientific validation and KG publication remain gated.",
            ),
        ).as_dict(),
    }


async def acquire_for_swarm_issue(
    *,
    issue_number,
    repository,
    run_id,
    run_attempt,
    comment_id,
    read_issue,
    read_lease,
    **services,
):
    """Execute under the canonical Swarm lease, re-reading before each boundary.

    Read callbacks are supplied by the authenticated canonical worker, never by
    source text. This does not claim a lease, settle an issue, or start a loop.
    """
    from app.provider_reservoir.routing import route_task
    from scripts.oc_swarm_claim import verify_worker_claim

    if repository != "jsp1440/orchid-calyx-backend":
        raise AcquisitionBlocked("CANONICAL_REPOSITORY_REQUIRED")

    def verify():
        issue = read_issue(issue_number)
        receipt = read_lease(comment_id)
        if issue.get("number") != issue_number:
            raise AcquisitionBlocked("ISSUE_IDENTITY_MISMATCH")
        if (
            "firecrawl-acquisition"
            not in route_task(issue).blocking_provider_capabilities
        ):
            raise AcquisitionBlocked("ACQUISITION_CAPABILITY_REQUIRED")
        if (receipt.get("user") or {}).get("login") != "github-actions[bot]":
            raise AcquisitionBlocked("CANONICAL_LEASE_AUTHOR_REQUIRED")
        if (
            receipt.get("issue_url")
            != f"https://api.github.com/repos/{repository}/issues/{issue_number}"
        ):
            raise AcquisitionBlocked("LEASE_ISSUE_MISMATCH")
        verify_worker_claim(
            issue,
            receipt,
            repository=repository,
            run_id=run_id,
            run_attempt=run_attempt,
            comment_id=comment_id,
        )

    return await acquire_matrix_sources(
        task_id=f"{repository}#{issue_number}", verify_lease=verify, **services
    )
