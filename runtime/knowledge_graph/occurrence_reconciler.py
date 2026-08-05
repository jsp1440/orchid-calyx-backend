"""GBIF/iNaturalist identifier-to-canonical-taxon reconciliation.

Maps external source identifiers (``taxonKey`` from GBIF, ``taxon_id`` from
iNaturalist) to the canonical taxon ids held in a
``CanonicalRegistry`` (built from the World Plants / Hassler backbone).

The reconciler tries resolution strategies in order of confidence:

1. **External authority mapping** — the registry stores GBIF/iNat external ids
   as ``AuthorityMapping`` records attached to accepted canonical taxa.  An
   exact ``external_id`` match produces ``reconciliation_method: exact_authority_id``.
2. **Scientific name lookup** — the normalized scientific name from the
   occurrence record is looked up in the registry's ``name_index``.  A hit
   produces ``reconciliation_method: canonical_name_lookup``.
3. **No match** — the record is placed in the unresolved review queue with
   ``reconciliation_method: unresolved``.

Usage::

    registry = build_canonical_registry(load_rows, synonym_rows)
    reconciler = OccurrenceCanonicalReconciler(registry)
    outcome = reconciler.reconcile(record)
    if outcome.canonical_taxon_id is not None:
        persistence.update_canonical_taxon_id(
            source=record["source"],
            source_record_id=record["source_record_id"],
            canonical_taxon_id=str(outcome.canonical_taxon_id),
        )
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from runtime.knowledge_graph.canonical_taxonomy import (
    CanonicalRegistry,
    CanonicalTaxon,
    canonical_name_of,
)

# Map source name → authority label stored in AuthorityMapping
_SOURCE_AUTHORITY: dict[str, str] = {
    "gbif": "GBIF",
    "inaturalist": "GBIF",  # iNat records often carry GBIF taxon keys
    "inat": "GBIF",
}

# Occurrence record field carrying the external taxon key
_SOURCE_TAXON_KEY_FIELD: dict[str, str] = {
    "gbif": "taxon_key",
    "inaturalist": "taxon_key",
    "inat": "taxon_key",
}


@dataclass(frozen=True)
class ReconciliationOutcome:
    source: str
    source_record_id: str
    canonical_taxon_id: int | None
    canonical_name: str | None
    reconciliation_method: str  # exact_authority_id | canonical_name_lookup | unresolved
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def resolved(self) -> bool:
        return self.canonical_taxon_id is not None


class OccurrenceCanonicalReconciler:
    """Reconcile occurrence records to canonical taxa.

    Builds two secondary indexes from the registry on construction
    (``O(n)``); individual reconciliation calls are ``O(1)``.

    Parameters
    ----------
    registry:
        The active ``CanonicalRegistry`` built from the World Plants release.
    """

    def __init__(self, registry: CanonicalRegistry) -> None:
        self._registry = registry
        # secondary index: authority → {external_id → canonical_taxon_id}
        self._authority_index: dict[str, dict[str, int]] = {}
        for taxon in registry.taxa.values():
            # Only resolve to accepted taxa — synonyms redirect
            accepted = registry.resolve(taxon.canonical_name)
            if accepted is None:
                accepted = taxon
            for mapping in taxon.authority_mappings:
                authority = mapping.authority.upper()
                self._authority_index.setdefault(authority, {})[
                    mapping.external_id
                ] = accepted.canonical_id

    def reconcile(self, record: dict[str, Any]) -> ReconciliationOutcome:
        """Attempt to resolve *record* to a canonical taxon.

        The record must contain at minimum:
        - ``source`` (e.g. ``"gbif"``, ``"inaturalist"``)
        - ``source_record_id``
        - optionally ``taxon_key``, ``scientific_name``, ``accepted_name``
        """
        source = str(record.get("source") or "").lower()
        source_record_id = str(record.get("source_record_id") or "")

        # Strategy 1: exact external authority id match
        taxon_key_field = _SOURCE_TAXON_KEY_FIELD.get(source, "taxon_key")
        taxon_key = record.get(taxon_key_field) or record.get("taxon_key")
        if taxon_key is not None:
            authority = _SOURCE_AUTHORITY.get(source, "GBIF")
            auth_idx = self._authority_index.get(authority, {})
            canonical_id = auth_idx.get(str(taxon_key))
            if canonical_id is not None:
                taxon = self._registry.taxa.get(canonical_id)
                return ReconciliationOutcome(
                    source=source,
                    source_record_id=source_record_id,
                    canonical_taxon_id=canonical_id,
                    canonical_name=taxon.canonical_name if taxon else None,
                    reconciliation_method="exact_authority_id",
                    confidence=0.99,
                )

        # Strategy 2: name lookup (try accepted_name first, then scientific_name)
        for name_field in ("accepted_name", "scientific_name"):
            raw_name = record.get(name_field)
            if not raw_name:
                continue
            resolved = self._registry.resolve(str(raw_name))
            if resolved is not None:
                return ReconciliationOutcome(
                    source=source,
                    source_record_id=source_record_id,
                    canonical_taxon_id=resolved.canonical_id,
                    canonical_name=resolved.canonical_name,
                    reconciliation_method="canonical_name_lookup",
                    confidence=0.9,
                )

        return ReconciliationOutcome(
            source=source,
            source_record_id=source_record_id,
            canonical_taxon_id=None,
            canonical_name=None,
            reconciliation_method="unresolved",
            confidence=0.0,
        )

    def reconcile_batch(
        self, records: list[dict[str, Any]]
    ) -> tuple[list[ReconciliationOutcome], list[ReconciliationOutcome]]:
        """Reconcile a list of records.

        Returns ``(resolved, unresolved)`` outcome lists.
        """
        resolved: list[ReconciliationOutcome] = []
        unresolved: list[ReconciliationOutcome] = []
        for record in records:
            outcome = self.reconcile(record)
            (resolved if outcome.resolved else unresolved).append(outcome)
        return resolved, unresolved

    def reconciliation_summary(
        self, records: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Return a summary dict suitable for mission control reporting."""
        resolved, unresolved = self.reconcile_batch(records)
        total = len(records)
        by_method: dict[str, int] = {}
        for outcome in resolved:
            by_method[outcome.reconciliation_method] = (
                by_method.get(outcome.reconciliation_method, 0) + 1
            )
        return {
            "contract": "calyx-occurrence-canonical-reconciliation-v1",
            "total": total,
            "resolved": len(resolved),
            "unresolved": len(unresolved),
            "resolution_rate": round(len(resolved) / total, 4) if total else 0.0,
            "by_method": by_method,
            "unresolved_records": [o.to_dict() for o in unresolved[:200]],
            "production_graph_mutation": False,
        }
