"""Cache-first wrapper for Firecrawl federation reconnaissance.

All module consumers should use this service instead of invoking
FirecrawlFederationMapper directly. The ledger coalesces duplicate requests,
blocks retry storms, and records Firecrawl credit usage/provenance.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy.orm import Session

from app.source_federation.acquisition import (
    AcquisitionRecord,
    AcquisitionRequest,
    canonicalize_url,
)
from app.source_federation.acquisition_ledger import AcquisitionLedger, StaleLeaseError

from .firecrawl_mapper import FederationSourceProfile, FirecrawlFederationMapper

logger = logging.getLogger(__name__)


def profile_from_payload(payload_json: str) -> FederationSourceProfile:
    """Rebuild a profile from the ledger's cached ``payload_json``."""
    data = json.loads(payload_json)
    return FederationSourceProfile(
        **{
            **data,
            "urls": tuple(data["urls"]),
            "url_classes": {
                key: tuple(value) for key, value in data["url_classes"].items()
            },
            "candidate_identifiers": {
                key: tuple(value)
                for key, value in data["candidate_identifiers"].items()
            },
            "api_download_hints": tuple(data["api_download_hints"]),
            "terms_license_hints": tuple(data["terms_license_hints"]),
        }
    )


class SharedFirecrawlFederationService:
    def __init__(
        self,
        session: Session,
        *,
        mapper: FirecrawlFederationMapper | None = None,
        worker_id: str = "firecrawl-federation",
    ) -> None:
        self.ledger = AcquisitionLedger(session)
        self.mapper = mapper or FirecrawlFederationMapper()
        self.worker_id = worker_id

    def map_source(
        self,
        *,
        consumer_module: str,
        source_id: str,
        root_url: str,
        search: str | None = None,
        limit: int = 100,
        sitemap: str = "include",
        include_subdomains: bool = False,
        force_refresh: bool = False,
    ) -> tuple[str, FederationSourceProfile | None]:
        request = self.acquisition_request(
            consumer_module=consumer_module,
            root_url=root_url,
            search=search,
            limit=limit,
            sitemap=sitemap,
            include_subdomains=include_subdomains,
            force_refresh=force_refresh,
        )
        claim = self.ledger.claim(request, worker_id=self.worker_id)
        if claim.action == "cache_hit":
            cached = self.ledger.cached_payload(request.key)
            if cached:
                return "cache_hit", profile_from_payload(cached)
            raise RuntimeError("completed acquisition is missing its cached payload")
        if claim.action != "acquired_lease":
            return claim.action, None

        try:
            profile = self.mapper.map_source(
                source_id=source_id,
                root_url=root_url,
                search=search,
                limit=limit,
                sitemap=sitemap,
                include_subdomains=include_subdomains,
            )
        except Exception:
            # Only a failed provider call is a failure. Nothing after a
            # successful (paid) call may reach ``fail()``: it would discard
            # the result and its credit and invite a second paid call.
            try:
                self.ledger.fail(claim)
            except StaleLeaseError:
                # Superseded while the call ran: the row belongs to the live
                # holder and must not be touched. The original error is still
                # what the caller sees.
                pass
            raise
        # Firecrawl Map is one credit per successful call under the current
        # operational contract. Keep accounting explicit here.
        credits_spent = 1
        try:
            payload = json.dumps(profile.to_dict(), sort_keys=True).encode("utf-8")
            record = AcquisitionRecord.completed(
                request=request,
                content=payload,
                provenance={
                    "retrieval_method": "firecrawl_map",
                    "source_id": source_id,
                    "root_url": root_url,
                    "scientific_status": "reconnaissance_only",
                },
                credits_spent=credits_spent,
            )
            self.ledger.complete(
                record, lease=claim, payload_json=payload.decode("utf-8")
            )
        except StaleLeaseError as exc:
            # Fail closed: our lease was superseded while the call ran, so the
            # live holder's result owns the cache. This late result is not
            # persisted and is not handed on without ledger provenance, but
            # the credit it cost is reported rather than lost silently.
            logger.warning(
                "firecrawl acquisition superseded: resource_key=%s worker=%s "
                "consumer=%s unrecorded_credits=%d",
                exc.resource_key,
                exc.lease_holder,
                consumer_module,
                exc.unrecorded_credits,
            )
            return "stale_lease", None
        except Exception:
            # The paid call succeeded but the ledger write did not. Do NOT
            # call fail(): leave the lease to expire and report the credit.
            logger.error(
                "firecrawl acquisition result not recorded: resource_key=%s "
                "worker=%s consumer=%s unrecorded_credits=%d",
                request.key,
                self.worker_id,
                consumer_module,
                credits_spent,
            )
            raise
        return "fetched", profile

    @classmethod
    def acquisition_request(
        cls,
        *,
        consumer_module: str,
        root_url: str,
        search: str | None = None,
        limit: int = 100,
        sitemap: str = "include",
        include_subdomains: bool = False,
        force_refresh: bool = False,
    ) -> AcquisitionRequest:
        """The ledger request (and so the ``resource_key``) ``map_source`` uses."""
        return AcquisitionRequest(
            url=root_url,
            provider="firecrawl_map",
            consumer_module=consumer_module,
            stable_identifier=cls._request_identity(
                root_url=root_url,
                search=search,
                limit=limit,
                sitemap=sitemap,
                include_subdomains=include_subdomains,
            ),
            force_refresh=force_refresh,
        )

    @staticmethod
    def _request_identity(
        *,
        root_url: str,
        search: str | None,
        limit: int,
        sitemap: str,
        include_subdomains: bool,
    ) -> str:
        return json.dumps(
            {
                "url": canonicalize_url(root_url),
                "search": search,
                "limit": limit,
                "sitemap": sitemap,
                "include_subdomains": include_subdomains,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
