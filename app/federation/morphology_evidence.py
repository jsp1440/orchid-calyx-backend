"""Budget-guarded extraction of factual morphological evidence via Firecrawl.

Extends the shared Firecrawl federation infrastructure (FIRECRAWL-FEDERATION-001)
from map-only reconnaissance to *controlled* factual text extraction, under the
same architectural invariant as the shared acquisition layer:
CACHE-FIRST / FETCH-ONCE / EXTRACT-ONCE / REUSE-EVERYWHERE / PROVENANCE-ALWAYS.

Hard governance rules enforced here:
- only sources with an explicit, reviewed policy (terms reviewed + robots
  compliant) may be queried; unknown or unreviewed sources fail closed;
- a strict credit budget is checked against the shared ledger before any
  provider call; exhaustion blocks new calls but never cache reads;
- identical requests dedupe through the shared acquisition ledger, so a second
  consumer spends zero credits;
- only bounded verbatim text excerpts are retained — never full articles and
  never images (no cloning of copyrighted photo libraries or long-form text);
- extracted statements are ``literature_excerpt_unverified`` and require review
  before they can inform any Matrix registry or scientific claim.

Production wiring passes the shared ``AcquisitionLedger`` (SQLAlchemy-backed);
bounded tests and the offline demo use ``InMemoryAcquisitionLedger``.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Callable, Mapping, Protocol

from app.source_federation.acquisition import AcquisitionRecord, AcquisitionRequest

SCHEMA_VERSION = "morphology-evidence/v1"
PROVIDER = "firecrawl_scrape"
DEFAULT_EXCERPT_LIMIT = 280


@dataclass(frozen=True, slots=True)
class SourcePolicy:
    """Explicit per-source permission record. Absence means not permitted."""

    source_id: str
    root_url: str
    terms_reviewed: bool
    robots_compliant: bool
    attribution: str


@dataclass(frozen=True, slots=True)
class ClaimResult:
    action: str  # cache_hit | acquired_lease | in_flight | retry_blocked
    row_id: int
    resource_key: str


class LedgerLike(Protocol):
    def claim(self, request: AcquisitionRequest, *, worker_id: str) -> ClaimResult: ...
    def cached_payload(self, resource_key: str) -> str | None: ...
    def complete(self, record: AcquisitionRecord, *, payload_json: str | None = None) -> None: ...
    def fail(self, resource_key: str) -> None: ...
    def metrics(self) -> dict[str, int]: ...


class InMemoryAcquisitionLedger:
    """Bounded in-memory ledger for tests/offline demos (no durable persistence)."""

    def __init__(self) -> None:
        self._rows: dict[str, dict[str, Any]] = {}
        self._next_id = 1

    def keys(self) -> list[str]:
        return sorted(self._rows)

    def claim(self, request: AcquisitionRequest, *, worker_id: str) -> ClaimResult:
        row = self._rows.get(request.key)
        if row is None:
            row = {
                "status": "leased",
                "payload_json": None,
                "credits_spent": 0,
                "failure_count": 0,
            }
            self._rows[request.key] = row
            row_id = self._next_id
            self._next_id += 1
            return ClaimResult("acquired_lease", row_id, request.key)
        if row["status"] == "complete" and not request.force_refresh:
            return ClaimResult("cache_hit", 0, request.key)
        if row["status"] == "leased":
            return ClaimResult("in_flight", 0, request.key)
        row["status"] = "leased"
        return ClaimResult("acquired_lease", 0, request.key)

    def cached_payload(self, resource_key: str) -> str | None:
        row = self._rows.get(resource_key)
        if row and row["status"] == "complete":
            return row["payload_json"]
        return None

    def complete(self, record: AcquisitionRecord, *, payload_json: str | None = None) -> None:
        row = self._rows[record.key]
        row["status"] = "complete"
        row["payload_json"] = payload_json
        row["credits_spent"] += record.credits_spent

    def fail(self, resource_key: str) -> None:
        row = self._rows[resource_key]
        row["status"] = "failed"
        row["failure_count"] += 1

    def metrics(self) -> dict[str, int]:
        return {
            "resources": len(self._rows),
            "completed": sum(r["status"] == "complete" for r in self._rows.values()),
            "credits_spent": sum(r["credits_spent"] for r in self._rows.values()),
            "failures": sum(r["failure_count"] for r in self._rows.values()),
        }


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]


_UNIT_SUFFIXES = {"mm", "cm", "m", "deg", "degree", "degrees", "ratio", "proportion"}


def _character_needle(character: str) -> str:
    tokens = str(character).casefold().replace("_", " ").split()
    if tokens and tokens[-1] in _UNIT_SUFFIXES:
        tokens = tokens[:-1]
    return " ".join(tokens)


def extract_morphological_statements(
    text: str,
    characters: list[str],
    *,
    excerpt_limit: int = DEFAULT_EXCERPT_LIMIT,
) -> list[dict[str, Any]]:
    """Return bounded verbatim excerpts mentioning each requested character.

    This is factual text location only: it never infers a character state value,
    never summarizes, and never retains more than ``excerpt_limit`` characters
    of source text per character.
    """
    items: list[dict[str, Any]] = []
    sentences = _sentences(text)
    for character in characters:
        needle = _character_needle(character)
        if not needle:
            continue
        for sentence in sentences:
            if needle in sentence.casefold():
                truncated = len(sentence) > excerpt_limit
                items.append(
                    {
                        "character": str(character),
                        "excerpt": sentence[:excerpt_limit],
                        "excerpt_truncated": truncated,
                    }
                )
                break
    return items


def plan_evidence_acquisition(
    characters: list[str],
    existing_coverage: Mapping[str, list[dict[str, Any]]],
) -> dict[str, list[str]]:
    """Reuse-before-pay plan: characters with existing governed evidence are skipped.

    ``existing_coverage`` maps a character id to already-held governed evidence
    references (knowledge-graph assertions, source records, registry states).
    Only characters with no existing coverage may proceed to provider calls.
    """
    skip: list[str] = []
    needed: list[str] = []
    for character in characters:
        if existing_coverage.get(character):
            skip.append(character)
        else:
            needed.append(character)
    return {"skip_provider_call": skip, "needs_acquisition": needed}


class MorphologyEvidenceService:
    """Controlled morphological evidence extraction over the shared ledger."""

    def __init__(
        self,
        ledger: LedgerLike,
        *,
        extractor: Callable[..., str],
        policies: Mapping[str, SourcePolicy],
        max_credits: int,
        worker_id: str = "morphology-evidence",
        excerpt_limit: int = DEFAULT_EXCERPT_LIMIT,
    ) -> None:
        if max_credits < 0:
            raise ValueError("max_credits must be >= 0")
        self.ledger = ledger
        self.extractor = extractor
        self.policies = dict(policies)
        self.max_credits = max_credits
        self.worker_id = worker_id
        self.excerpt_limit = excerpt_limit

    def extract_morphology(
        self,
        *,
        consumer_module: str,
        source_id: str,
        url: str,
        taxon_name: str,
        characters: list[str],
    ) -> dict[str, Any]:
        policy = self.policies.get(source_id)
        if policy is None or not (policy.terms_reviewed and policy.robots_compliant):
            return {
                "status": "source_not_permitted",
                "reason": "source requires explicit reviewed terms and robots clearance",
                "source_id": source_id,
                "credits_spent": 0,
                "items": [],
            }
        if self.ledger.metrics()["credits_spent"] >= self.max_credits:
            return {
                "status": "budget_exhausted",
                "reason": f"credit budget {self.max_credits} reached; cache reads remain available",
                "source_id": source_id,
                "credits_spent": 0,
                "items": [],
            }

        request = AcquisitionRequest(
            url=url,
            provider=PROVIDER,
            consumer_module=consumer_module,
            stable_identifier=self._identity(source_id, taxon_name, characters),
        )
        claim = self.ledger.claim(request, worker_id=self.worker_id)
        if claim.action == "cache_hit":
            cached = self.ledger.cached_payload(request.key)
            if cached is None:
                raise RuntimeError("completed acquisition is missing its cached payload")
            payload = json.loads(cached)
            return {
                "status": "cache_hit",
                "source_id": source_id,
                "credits_spent": 0,
                "items": payload["items"],
                "retrieved_at": payload["retrieved_at"],
            }
        if claim.action != "acquired_lease":
            return {
                "status": claim.action,
                "source_id": source_id,
                "credits_spent": 0,
                "items": [],
            }

        try:
            text = self.extractor(url=request.canonical_url, taxon_name=taxon_name)
            if not isinstance(text, str) or not text.strip():
                raise ValueError("extractor returned no text")
            statements = extract_morphological_statements(
                text, characters, excerpt_limit=self.excerpt_limit
            )
            retrieved_at = _now()
            items = [
                {
                    **item,
                    "source_id": source_id,
                    "source_url": request.canonical_url,
                    "taxon_name": taxon_name,
                    "attribution": policy.attribution,
                    "retrieved_at": retrieved_at,
                    "evidence_class": "literature_excerpt_unverified",
                    "review_state": "review_required",
                }
                for item in statements
            ]
            payload = json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "retrieved_at": retrieved_at,
                    "items": items,
                },
                sort_keys=True,
            )
            record = AcquisitionRecord.completed(
                request=request,
                content=payload.encode("utf-8"),
                provenance={
                    "retrieval_method": PROVIDER,
                    "source_id": source_id,
                    "source_url": request.canonical_url,
                    "attribution": policy.attribution,
                    "scientific_status": "literature_excerpt_unverified",
                },
                # One Firecrawl scrape credit per successful extraction under the
                # current operational contract. Accounting stays explicit.
                credits_spent=1,
            )
            self.ledger.complete(record, payload_json=payload)
            return {
                "status": "fetched",
                "source_id": source_id,
                "credits_spent": 1,
                "items": items,
                "retrieved_at": retrieved_at,
            }
        except Exception:
            self.ledger.fail(request.key)
            raise

    @staticmethod
    def _identity(source_id: str, taxon_name: str, characters: list[str]) -> str:
        return "|".join(
            [
                source_id.strip().casefold(),
                taxon_name.strip().casefold(),
                ",".join(sorted(str(c).strip().casefold() for c in characters)),
            ]
        )
