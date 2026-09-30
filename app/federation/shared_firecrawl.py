"""Cache-first wrapper for Firecrawl federation reconnaissance.

All module consumers should use this service instead of invoking
FirecrawlFederationMapper directly. The ledger coalesces duplicate requests,
blocks retry storms, and records Firecrawl credit usage/provenance.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.source_federation.acquisition import AcquisitionRecord, AcquisitionRequest, canonicalize_url
from app.source_federation.acquisition_ledger import AcquisitionLedger

from .firecrawl_mapper import FirecrawlFederationMapper, FederationSourceProfile


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
        request = AcquisitionRequest(
            url=root_url,
            provider="firecrawl_map",
            consumer_module=consumer_module,
            stable_identifier=self._request_identity(
                root_url=root_url,
                search=search,
                limit=limit,
                sitemap=sitemap,
                include_subdomains=include_subdomains,
            ),
            force_refresh=force_refresh,
        )
        claim = self.ledger.claim(request, worker_id=self.worker_id)
        if claim.action == "cache_hit":\n            cached = self.ledger.cached_payload(request.key)\n            if cached:\n                data = json.loads(cached)\n                profile = FederationSourceProfile(**{\n                    **data,\n                    "urls": tuple(data["urls"]),\n                    "url_classes": {k: tuple(v) for k, v in data["url_classes"].items()},\n                    "candidate_identifiers": {k: tuple(v) for k, v in data["candidate_identifiers"].items()},\n                    "api_download_hints": tuple(data["api_download_hints"]),\n                    "terms_license_hints": tuple(data["terms_license_hints"]),\n                })\n                return "cache_hit", profile\n            raise RuntimeError("completed acquisition is missing its cached payload")\n        if claim.action != "acquired_lease":\n            return claim.action, None\n
        try:
            profile = self.mapper.map_source(
                source_id=source_id,
                root_url=root_url,
                search=search,
                limit=limit,
                sitemap=sitemap,
                include_subdomains=include_subdomains,
            )
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
                # Firecrawl Map is one credit per successful call under the
                # current operational contract. Keep accounting explicit here.
                credits_spent=1,
            )
            self.ledger.complete(record, payload_json=payload.decode("utf-8"))\n            return "fetched", profile
        except Exception:
            self.ledger.fail(request.key)
            raise

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
