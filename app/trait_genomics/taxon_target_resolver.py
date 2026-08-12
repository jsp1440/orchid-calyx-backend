from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Literal

import psycopg
from psycopg.rows import dict_row

from app.species_dossier.service import normalize_scientific_name

from .molecular_harvester import MolecularHarvestTarget


ResolutionStatus = Literal["resolved", "unresolved", "ambiguous", "invalid"]


@dataclass(frozen=True)
class TaxonTargetResolution:
    status: ResolutionStatus
    query_name: str
    normalized_name: str | None
    target: MolecularHarvestTarget | None
    candidates: tuple[dict[str, str], ...] = ()
    explanation: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "query_name": self.query_name,
            "normalized_name": self.normalized_name,
            "target": self.target.model_dump(mode="json") if self.target else None,
            "candidates": list(self.candidates),
            "explanation": self.explanation,
            "canonical_source": "public.orchid_taxonomy",
            "automatic_fuzzy_matching": False,
        }


class CanonicalTaxonTargetResolver:
    """Resolve exact orchid names to canonical operational taxon identifiers.

    The operational species surfaces use ``public.orchid_taxonomy.id`` as the
    canonical taxon identifier. Resolution is deliberately fail-closed: exact
    normalized binomial/infraspecific identity is required and more than one
    canonical row is returned as ambiguous rather than guessed.
    """

    def __init__(
        self,
        database_url: str | None = None,
        *,
        connection_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.database_url = database_url or os.getenv("DATABASE_URL")
        self.connection_factory = connection_factory or psycopg.connect

    def _connect(self):
        if not self.database_url:
            raise RuntimeError("DATABASE_URL is required for canonical TIG taxon resolution")
        return self.connection_factory(self.database_url, row_factory=dict_row)

    @staticmethod
    def _normalized_row_name(value: str) -> str | None:
        return normalize_scientific_name(value)

    @staticmethod
    def _candidate(row: dict[str, Any]) -> dict[str, str]:
        return {
            "canonical_taxon_id": str(row["id"]),
            "scientific_name": str(row["scientific_name"]),
        }

    def resolve(self, scientific_name: str) -> TaxonTargetResolution:
        query_name = " ".join((scientific_name or "").split())
        normalized = normalize_scientific_name(query_name)
        if normalized is None:
            return TaxonTargetResolution(
                status="invalid",
                query_name=query_name,
                normalized_name=None,
                target=None,
                explanation="A binomial or supported infraspecific scientific name is required.",
            )

        genus = normalized.split()[0]
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.orchid_taxonomy') IS NOT NULL AS present")
            present = cur.fetchone()
            if not present or not present["present"]:
                raise RuntimeError("Canonical table public.orchid_taxonomy is unavailable")
            cur.execute(
                """
                SELECT id, scientific_name, genus
                FROM public.orchid_taxonomy
                WHERE lower(genus) = lower(%s)
                  AND lower(scientific_name) LIKE lower(%s)
                ORDER BY id
                LIMIT 100
                """,
                (genus, f"{genus} %"),
            )
            rows = [dict(row) for row in cur.fetchall()]

        matches = [
            row
            for row in rows
            if self._normalized_row_name(str(row.get("scientific_name") or "")) == normalized
        ]
        if not matches:
            return TaxonTargetResolution(
                status="unresolved",
                query_name=query_name,
                normalized_name=normalized,
                target=None,
                explanation=(
                    "No canonical public.orchid_taxonomy row has the same normalized scientific name. "
                    "No synonym or fuzzy substitution was attempted."
                ),
            )
        if len(matches) > 1:
            return TaxonTargetResolution(
                status="ambiguous",
                query_name=query_name,
                normalized_name=normalized,
                target=None,
                candidates=tuple(self._candidate(row) for row in matches),
                explanation=(
                    "Multiple canonical rows share the normalized scientific name; explicit human "
                    "selection is required before literature harvesting."
                ),
            )

        row = matches[0]
        target = MolecularHarvestTarget(
            canonical_taxon_id=str(row["id"]),
            scientific_name=normalized,
        )
        return TaxonTargetResolution(
            status="resolved",
            query_name=query_name,
            normalized_name=normalized,
            target=target,
            candidates=(self._candidate(row),),
            explanation="Resolved by exact normalized name against public.orchid_taxonomy.",
        )

    def resolve_or_raise(self, scientific_name: str) -> MolecularHarvestTarget:
        resolution = self.resolve(scientific_name)
        if resolution.target is not None and resolution.status == "resolved":
            return resolution.target
        candidates = ", ".join(
            f"{item['canonical_taxon_id']}={item['scientific_name']}"
            for item in resolution.candidates
        )
        suffix = f" Candidates: {candidates}" if candidates else ""
        raise ValueError(
            f"Canonical taxon resolution {resolution.status} for {scientific_name!r}: "
            f"{resolution.explanation}{suffix}"
        )
