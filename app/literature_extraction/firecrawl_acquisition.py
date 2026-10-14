"""Firecrawl capability composition over the existing literature/evidence services.

No queue or scientific store is owned here. The canonical worker supplies its
verified lease, source-registration/binding boundary, and persistent services.
Missing source identities block; this module never manufactures database IDs.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

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
    target_names=(),
    corpus_audit=None,
    load_held_source=None,
    before_acquire=None,
    required_predicates=(),
):
    """Acquire once per source, extracting multiple taxa without species crawls.

    ``register_and_bind`` must use canonical intake identities and return a
    CanonicalLiteratureSourceBinding with exact integrity. Production callers
    use the existing DocumentIntelligenceBindingResolver after source import.
    Service mutations must run within their repository's existing write scope.
    """
    verify_lease()
    provider.lease_check = verify_lease
    if corpus_audit is None and not provider.config.dry_run:
        raise AcquisitionBlocked("EXISTING_CORPUS_AUDIT_REQUIRED")
    receipts = []
    processed_hashes = set()
    metrics = {
        "existing_documents_reused": 0,
        "new_documents_acquired": 0,
        "duplicate_documents_avoided": 0,
        "corpus_audit_available": corpus_audit is not None,
        "existing_candidates_reused": 0,
        "new_candidates_created": 0,
        "structured_claims_extracted": 0,
        "structured_claims_reused": 0,
        "existing_documents_reprocessed": 0,
        "existing_sources_checked": 0,
    }

    async def process_source(source, *, reused=False):
        if source.content_hash in processed_hashes:
            metrics["duplicate_documents_avoided"] += 1
            return
        processed_hashes.add(source.content_hash)
        verify_lease()
        existing = literature_repository.get("paper-" + source.content_hash)
        if existing is not None and existing.source.origin_uri != source.url:
            from .firecrawl_provider import AcquiredSource

            source = AcquiredSource(
                existing.source.origin_uri, source.markdown, source.mocked
            )
            metrics["duplicate_documents_avoided"] += 1
        registry = ExtractorRegistry(
            [MetadataExtractor(), CanonicalMorphologyExtractor(taxonomy)]
        )
        release = taxonomy.canonical_release
        if release is None:
            raise AcquisitionBlocked("CANONICAL_TAXONOMY_RELEASE_REQUIRED")
        reusable_analysis = bool(reused and existing is not None and existing.claims)
        if reusable_analysis:
            for entity in existing.entities:
                if entity.entity_type != "taxon":
                    continue
                resolved = taxonomy.resolve(entity.name)
                if resolved is None or resolved.status != "accepted":
                    reusable_analysis = False
                    break
                expected = f"{resolved.provenance.get('identity_namespace', 'world_plants')}:{resolved.canonical_id}"
                if not any(
                    identifier.scheme == "local" and identifier.value == expected
                    for identifier in entity.external_ids
                ):
                    reusable_analysis = False
                    break
        if reusable_analysis:
            paper = existing
        else:
            if reused:
                metrics["existing_documents_reprocessed"] += 1
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
                        acquisition_method=(
                            "existing_corpus"
                            if reused
                            else "firecrawl_v2_fixture"
                            if source.mocked
                            else "firecrawl_v2"
                        ),
                    ),
                )
        metrics[
            "structured_claims_reused"
            if reusable_analysis
            else "structured_claims_extracted"
        ] += len(paper.claims)
        if not paper.claims:
            metrics[
                "existing_documents_reused" if reused else "new_documents_acquired"
            ] += 1
            return
        verify_lease()
        binding = register_and_bind(source, paper)
        binding.validate_integrity(paper, source.markdown.encode())
        payload = asdict(binding)
        payload.pop("paper_id")

        def handoff_operation(paper=paper, payload=payload):
            before_ids = {
                candidate["candidate_id"]
                for candidate in handoff_service.candidate_repository.candidates
            }
            handoff = handoff_service.handoff(paper, LiteratureSourceBinding(**payload))
            metrics["existing_candidates_reused"] += len(
                set(handoff["candidate_ids"]) & before_ids
            )
            metrics["new_candidates_created"] += len(
                set(handoff["candidate_ids"]) - before_ids
            )
            repository = handoff_service.candidate_repository
            return (
                handoff,
                deepcopy(repository.candidates_for_run(handoff["candidate_run_id"])),
                deepcopy(repository.evidence_links),
            )

        repository = handoff_service.candidate_repository
        handoff, candidates, evidence_links = (
            repository.atomic(handoff_operation)
            if hasattr(repository, "atomic")
            else handoff_operation()
        )
        if handoff["state"] != "COMPLETED" or not handoff["candidate_ids"]:
            raise AcquisitionBlocked("CANDIDATE_HANDOFF_INCOMPLETE")
        inputs = []
        for candidate in candidates:
            links = [
                link
                for link in evidence_links
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
                        "provider": "existing_corpus" if reused else "firecrawl",
                        "taxonomy_snapshot": release.snapshot_id,
                    },
                    display_policy="METADATA_ONLY",
                )
            )
        verify_lease()

        def aggregate_operation(inputs=inputs):
            # Keep prior source assertions in the same subject/predicate cluster.
            # A later document cannot silently replace an earlier measurement.
            subjects = {(item.normalized_subject, item.predicate) for item in inputs}
            retained = {}
            for items in aggregation_service.repo.items.values():
                for item in items:
                    for candidate in item.get("candidates", []):
                        if (
                            candidate.normalized_subject,
                            candidate.predicate,
                        ) in subjects:
                            retained[
                                (candidate.candidate_id, candidate.candidate_version)
                            ] = candidate
            for candidate in inputs:
                retained[(candidate.candidate_id, candidate.candidate_version)] = (
                    candidate
                )
            plan = aggregation_service.preview(list(retained.values()))
            return plan, aggregation_service.execute(plan["aggregate_run_id"])

        aggregate_repository = aggregation_service.repo
        plan, result = (
            aggregate_repository.atomic(aggregate_operation)
            if hasattr(aggregate_repository, "atomic")
            else aggregate_operation()
        )
        if result["state"] != "COMPLETED":
            raise AcquisitionBlocked("AGGREGATION_INCOMPLETE")
        receipts.append(
            {
                "paper_id": paper.paper_id,
                "source_hash": source.content_hash,
                "source_url": source.url,
                "source_domain": urlsplit(source.url).hostname,
                "taxonomy_snapshot_id": release.snapshot_id,
                "taxonomy_source_hash": release.file_sha256,
                "taxon_names": sorted(
                    {
                        entity.name
                        for entity in paper.entities
                        if entity.entity_type == "taxon"
                    }
                ),
                "extracted_characters": sorted(
                    {candidate["predicate"] for candidate in candidates}
                ),
                "binding_fingerprint": binding.fingerprint,
                "analysis_id": paper.analysis_manifest.analysis_id,
                "revision_id": binding.revision_id,
                "extraction_run_id": binding.extraction_run_id,
                "anchor_ids": sorted(set(binding.anchor_ids.values())),
                "candidate_ids": handoff["candidate_ids"],
                "aggregate_run_id": plan["aggregate_run_id"],
                "mocked": source.mocked,
                "acquisition_origin": "existing_corpus" if reused else "firecrawl",
            }
        )
        metrics[
            "existing_documents_reused" if reused else "new_documents_acquired"
        ] += 1

    scoped_subjects = {
        f"local:{taxon.provenance.get('identity_namespace', 'world_plants')}:{taxon.canonical_id}"
        for taxon in taxonomy.accepted()
        if taxon.canonical_name.split()[0] == genus
        and (not target_names or taxon.canonical_name in target_names)
    }

    def anchored_characters():
        repository = aggregation_service.repo
        if hasattr(repository, "refresh"):
            repository.refresh()
        return {
            (candidate.normalized_subject, candidate.predicate)
            for run_id, items in repository.items.items()
            if repository.runs[run_id]["state"] == "COMPLETED"
            for item in items
            for candidate in item.get("candidates", [])
            if candidate.metadata.get("taxonomy_snapshot")
            == taxonomy.canonical_release.snapshot_id
            and candidate.source_anchor_ids
            and candidate.document_hash
            and candidate.normalized_subject in scoped_subjects
        }

    initial_characters = anchored_characters()
    initial_gaps = missing_morphology_requirements(
        taxonomy, genus, target_names, required_predicates, aggregation_service.repo
    )
    audit = None
    if corpus_audit is not None:
        audit = corpus_audit()
        if not audit.get("available") or not audit.get(
            "audit_complete", audit.get("complete")
        ):
            raise AcquisitionBlocked("EXISTING_CORPUS_AUDIT_UNAVAILABLE")
        metrics["existing_sources_checked"] = len(
            {
                identity.get("content_hash")
                or identity.get("doi")
                or identity.get("source_url")
                or (
                    identity.get("relation"),
                    identity.get("registry_id"),
                    identity.get("revision_id"),
                    index,
                )
                for index, identity in enumerate(audit.get("identities", []))
            }
        )
        if load_held_source is None:
            raise AcquisitionBlocked("EXISTING_CORPUS_LOADER_REQUIRED")
        for document in audit.get("documents", []):
            if not document.get("loadable"):
                continue
            verify_lease()
            await process_source(load_held_source(document), reused=True)
        # Re-read persistent evidence after reusing available sources.
        audit = corpus_audit()
        if not audit.get("available") or not audit.get(
            "audit_complete", audit.get("complete")
        ):
            raise AcquisitionBlocked("EXISTING_CORPUS_AUDIT_UNAVAILABLE")
    missing = missing_morphology_requirements(
        taxonomy, genus, target_names, required_predicates, aggregation_service.repo
    )
    metrics["remaining_gaps"] = missing
    decision = (
        "EXISTING_CORPUS_SUFFICIENT"
        if audit is not None and required_predicates and not missing
        else "EXISTING_CORPUS_INCOMPLETE"
    )
    needs_acquisition = audit is None or bool(missing)
    if needs_acquisition:
        if not provider.config.dry_run and not required_predicates:
            raise AcquisitionBlocked("EXPLICIT_PREDICATE_SCOPE_REQUIRED")
        if audit is not None and audit.get("blockers"):
            raise AcquisitionBlocked("EXISTING_CORPUS_REUSE_BLOCKED")
        verify_lease()
        if before_acquire is not None:
            before_acquire()
        missing_predicates = (
            sorted(
                {
                    predicate
                    for gap in missing
                    for predicate in gap["missing_predicates"]
                }
            )
            if required_predicates
            else []
        )
        urls = provider.search(
            genus,
            task_id=task_id,
            target_names=target_names,
            required_predicates=missing_predicates,
        )
        for url in urls:
            verify_lease()
            metadata = getattr(provider, "search_results", {}).get(
                url, {"source_url": url}
            )
            if audit is not None and held_source_match(
                {**metadata, "source_url": url}, audit.get("identities", [])
            ):
                metrics["duplicate_documents_avoided"] += 1
                continue
            source = provider.scrape(url, task_id=task_id)
            if audit is not None and held_source_match(
                {"content_hash": source.content_hash}, audit.get("identities", [])
            ):
                metrics["duplicate_documents_avoided"] += 1
                continue
            await process_source(source)
    if not receipts:
        raise AcquisitionBlocked("NO_TRACEABLE_MORPHOLOGY_EVIDENCE")
    metrics["remaining_gaps"] = missing_morphology_requirements(
        taxonomy, genus, target_names, required_predicates, aggregation_service.repo
    )
    if required_predicates and metrics["remaining_gaps"]:
        # A successful transport is not successful work when the requested
        # taxon/predicate scope is still incomplete. Refuse settlement so the
        # durable worker releases/parks the claim instead of permanently
        # duplicate-suppressing an unresolved gap.
        raise AcquisitionBlocked("MORPHOLOGY_COVERAGE_INCOMPLETE")
    credit_receipt = provider.credit_receipt()
    reserved = credit_receipt["reserved"]
    remaining_ids = {gap["taxon_id"] for gap in metrics["remaining_gaps"]}
    newly_covered = (
        len({gap["taxon_id"] for gap in initial_gaps} - remaining_ids)
        if required_predicates
        else 0
    )
    metrics.update(
        existing_sources_used=len(
            {
                receipt["source_hash"]
                for receipt in receipts
                if receipt["acquisition_origin"] == "existing_corpus"
            }
        ),
        firecrawl_searches=provider.searches,
        firecrawl_pages=provider.documents,
        credits_reserved=reserved,
        credits_reported=credit_receipt["provider_reported"],
        new_taxa_covered=newly_covered,
        new_characters_extracted=len(anchored_characters() - initial_characters),
        duplicate_sources_avoided=metrics["duplicate_documents_avoided"],
        scientific_evidence_per_credit=metrics["new_candidates_created"] / reserved
        if reserved
        else None,
        evidence_per_credit_basis="new_review_pending_anchored_candidates_per_reserved_credit",
        zero_credit_reuse=provider.calls == 0 and metrics["existing_documents_reused"] > 0,
        efficiency_ranking="zero_credit_reuse"
        if provider.calls == 0 and metrics["existing_documents_reused"] > 0
        else "bounded_external_acquisition",
    )
    return {
        "status": "review_pending",
        "corpus_decision": decision,
        "coverage_scope": {
            "genus": genus,
            "target_names": list(target_names),
            "required_predicates": list(required_predicates),
            "explicit": bool(required_predicates),
            "full_matrix_coverage": False,
        },
        "sources": receipts,
        "corpus_metrics": metrics,
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

    def verify():
        return verify_swarm_acquisition_lease(
            issue_number=issue_number,
            repository=repository,
            run_id=run_id,
            run_attempt=run_attempt,
            comment_id=comment_id,
            read_issue=read_issue,
            read_lease=read_lease,
        )

    return await acquire_matrix_sources(
        task_id=f"{repository}#{issue_number}", verify_lease=verify, **services
    )


def verify_swarm_acquisition_lease(
    *,
    issue_number,
    repository,
    run_id,
    run_attempt,
    comment_id,
    read_issue,
    read_lease,
):
    """Shared backend preflight and per-boundary canonical claim verification."""
    from app.provider_reservoir.routing import route_task
    from scripts.oc_swarm_claim import verify_worker_claim

    if repository != "jsp1440/orchid-calyx-backend":
        raise AcquisitionBlocked("CANONICAL_REPOSITORY_REQUIRED")
    issue = read_issue(issue_number)
    receipt = read_lease(comment_id)
    if issue.get("number") != issue_number:
        raise AcquisitionBlocked("ISSUE_IDENTITY_MISMATCH")
    if "firecrawl-acquisition" not in route_task(issue).blocking_provider_capabilities:
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
    return issue


def missing_morphology_requirements(
    taxonomy, genus, target_names, predicates, repository
):
    """Acquired anchored assertions meet coverage, never scientific approval."""
    release = taxonomy.canonical_release
    if release is None:
        raise AcquisitionBlocked("CANONICAL_TAXONOMY_RELEASE_REQUIRED")
    if hasattr(repository, "refresh"):
        repository.refresh()
    names = set(target_names)
    taxa = [
        taxon
        for taxon in taxonomy.accepted()
        if taxon.rank == "species"
        and taxon.canonical_name.split()[0] == genus
        and (not names or taxon.canonical_name in names)
    ]
    covered = {}
    for run_id, items in repository.items.items():
        if repository.runs[run_id]["state"] != "COMPLETED":
            continue
        for item in items:
            for candidate in item.get("candidates", []):
                if (
                    candidate.metadata.get("taxonomy_snapshot") == release.snapshot_id
                    and candidate.source_anchor_ids
                    and candidate.document_hash
                ):
                    covered.setdefault(candidate.normalized_subject, set()).add(
                        candidate.predicate
                    )
    result = []
    for taxon in taxa:
        subject = f"local:{taxon.provenance.get('identity_namespace', 'world_plants')}:{taxon.canonical_id}"
        present = covered.get(subject, set())
        missing = (
            sorted(set(predicates) - present)
            if predicates
            else ([] if present else ["morphology_evidence"])
        )
        if missing:
            result.append(
                {
                    "taxon_name": taxon.canonical_name,
                    "taxon_id": taxon.canonical_id,
                    "missing_predicates": missing,
                }
            )
    return result


def held_source_match(candidate, identities):
    """Match stable supplied identities; metadata absence never invents a match."""
    import re
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    def url(value):
        if not value:
            return None
        parsed = urlsplit(str(value))
        return urlunsplit(
            (
                parsed.scheme.lower(),
                parsed.netloc.lower().rstrip("."),
                parsed.path.rstrip("/") or "/",
                urlencode(
                    sorted(
                        (key, val)
                        for key, val in parse_qsl(parsed.query)
                        if not key.lower().startswith("utm_")
                        and key.lower() not in {"fbclid", "gclid"}
                    )
                ),
                "",
            )
        )

    def doi(item):
        value = item.get("doi")
        if not value:
            match = re.search(
                r"10\.\d{4,9}/[^?#\s]+",
                str(item.get("source_url") or item.get("url") or ""),
                re.IGNORECASE,
            )
            value = match.group(0) if match else None
        return (
            re.sub(
                r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)",
                "",
                str(value),
                flags=re.IGNORECASE,
            )
            .lower()
            .strip()
            if value
            else None
        )

    def bibliography(item):
        title, authors, year = (
            item.get("title"),
            item.get("authors") or item.get("author"),
            item.get("year"),
        )
        if not title or not authors or not year:
            return None
        if isinstance(authors, (tuple, list)):
            authors = " ".join(str(author) for author in authors)
        normalize = lambda value: " ".join(re.findall(r"\w+", str(value).casefold()))
        return normalize(title), normalize(authors), str(year)

    for held in identities:
        for field in ("content_hash", "binding_fingerprint", "paper_id"):
            if candidate.get(field) and candidate[field] == held.get(field):
                return True
        if doi(candidate) and doi(candidate) == doi(held):
            return True
        if url(candidate.get("source_url") or candidate.get("url")) and url(
            candidate.get("source_url") or candidate.get("url")
        ) == url(held.get("source_url") or held.get("url")):
            return True
        if bibliography(candidate) and bibliography(candidate) == bibliography(held):
            return True
    return False
