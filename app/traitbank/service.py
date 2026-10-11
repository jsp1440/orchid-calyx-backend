"""Read-only TraitBank queries for routes, Calyx and the Matrix.

Every method reads; none writes. A database that cannot be reached is
reported as ``UNAVAILABLE`` (never as an empty result), and an unknown taxon
or trait as ``UNKNOWN``, matching ``oc-research-traits-v1`` semantics.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import psycopg

from runtime.matrix_relationship import RelationshipAssertion, build_relationship_matrix

from . import projection
from .contract import CONTRACT_VERSION
from .models import AssertionIn, TraitDefinitionIn
from .repository import TraitBankRepository, row_to_assertion, row_to_relation


def _public_assertion(
    row: dict[str, Any], definition: TraitDefinitionIn | None
) -> dict[str, Any]:
    a = row_to_assertion(row)
    data = a.model_dump(mode="json")
    data["value_text"] = projection.value_text(definition, a)
    data["statement"] = projection.describe(definition, a)
    data["confidence_state"] = "reported" if a.confidence is not None else "unknown"
    data["storage"] = {
        "batch_key": row.get("batch_key"),
        "producer": row.get("producer"),
        "record_sha256": row.get("record_sha256"),
        "stored_at": row["created_at"].isoformat() if row.get("created_at") else None,
    }
    return data


class TraitBankService:
    def __init__(self, repository: TraitBankRepository | None = None) -> None:
        self.repository = repository or TraitBankRepository()

    def _guard(self, fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        try:
            return fn()
        except (psycopg.Error, RuntimeError):
            return {"contract_version": CONTRACT_VERSION, "state": "UNAVAILABLE"}

    def _taxon(self, taxon_id: str) -> dict[str, Any] | None:
        found = self.repository.canonical_taxa([taxon_id]).get(taxon_id)
        return {"taxon_id": taxon_id, "name": found.name} if found else None

    # ------------------------------------------------------------- by taxon
    def taxon(self, taxon_id: str) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            taxon = self._taxon(taxon_id)
            if taxon is None:
                return {
                    "contract_version": CONTRACT_VERSION,
                    "state": "UNKNOWN",
                    "taxon": {"taxon_id": taxon_id},
                    "traits": [],
                }
            rows = self.repository.assertions(taxon_ids=[taxon_id])
            assertions = [row_to_assertion(r) for r in rows]
            definitions = self.repository.definitions(
                sorted({a.trait_id for a in assertions})
            )
            traits = []
            for trait_id, definition in sorted(definitions.items()):
                relations = [
                    row_to_relation(r) for r in self.repository.relations(trait_id)
                ]
                traits.append(
                    projection.summarize(definition, taxon_id, assertions, relations)
                )
            return {
                "contract_version": CONTRACT_VERSION,
                "state": "AVAILABLE" if traits else "ABSENT",
                "taxon": taxon,
                "traits": traits,
            }

        return self._guard(run)

    def species(self, name: str) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            taxon_id = self.repository.resolve_species(name)
            if taxon_id is None:
                return {
                    "contract_version": CONTRACT_VERSION,
                    "state": "UNKNOWN",
                    "taxon": {"name": name},
                    "traits": [],
                }
            return self.taxon(taxon_id)

        return self._guard(run)

    def genus(self, genus: str) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            ids = self.repository.genus_ids(genus)
            if not ids:
                return {
                    "contract_version": CONTRACT_VERSION,
                    "state": "UNKNOWN",
                    "genus": genus,
                    "taxa": [],
                }
            rows = self.repository.assertions(taxon_ids=ids)
            by_taxon: dict[str, dict[str, int]] = {}
            for r in rows:
                counts = by_taxon.setdefault(str(r["taxon_id"]), {})
                counts[r["trait_id"]] = counts.get(r["trait_id"], 0) + 1
            labels = self.repository.canonical_taxa(sorted(by_taxon))
            return {
                "contract_version": CONTRACT_VERSION,
                "state": "AVAILABLE" if by_taxon else "ABSENT",
                "genus": genus,
                "taxa": [
                    {
                        "taxon_id": t,
                        "name": labels[t].name if t in labels else None,
                        "assertion_counts": c,
                    }
                    for t, c in sorted(by_taxon.items())
                ],
            }

        return self._guard(run)

    # ---------------------------------------------------------- by character
    def character(self, trait_id: str, taxon_id: str | None = None) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            definition = self.repository.definitions([trait_id]).get(trait_id)
            if definition is None:
                return {
                    "contract_version": CONTRACT_VERSION,
                    "state": "UNKNOWN",
                    "trait_id": trait_id,
                }
            rows = self.repository.assertions(
                trait_id=trait_id, taxon_ids=[taxon_id] if taxon_id else None
            )
            assertions = [row_to_assertion(r) for r in rows]
            return {
                "contract_version": CONTRACT_VERSION,
                "state": "AVAILABLE" if rows else "ABSENT",
                "definition": definition.model_dump(mode="json"),
                "assertions": [_public_assertion(r, definition) for r in rows],
                "conflicts": projection.conflicts(assertions),
                "environment_relations": [
                    {
                        **row_to_relation(r).model_dump(mode="json"),
                        "text": row_to_relation(r).describe(),
                    }
                    for r in self.repository.relations(trait_id)
                ],
            }

        return self._guard(run)

    # ----------------------------------------------------- evidence/provenance
    def assertion(self, assertion_id: str) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            rows = self.repository.assertions(assertion_id=assertion_id, limit=1)
            if not rows:
                return {
                    "contract_version": CONTRACT_VERSION,
                    "state": "UNKNOWN",
                    "assertion_id": assertion_id,
                }
            definition = self.repository.definitions([rows[0]["trait_id"]]).get(
                rows[0]["trait_id"]
            )
            return {
                "contract_version": CONTRACT_VERSION,
                "state": "AVAILABLE",
                "assertion": _public_assertion(rows[0], definition),
            }

        return self._guard(run)

    def source(self, source_id: str) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            rows = self.repository.assertions(source_id=source_id)
            definitions = self.repository.definitions(
                sorted({r["trait_id"] for r in rows})
            )
            citations = sorted({r["citation"] for r in rows})
            return {
                "contract_version": CONTRACT_VERSION,
                "state": "AVAILABLE" if rows else "ABSENT",
                "source_id": source_id,
                "citations": citations,
                "licenses": sorted({r["license"] for r in rows}),
                "assertions": [
                    _public_assertion(r, definitions.get(r["trait_id"])) for r in rows
                ],
            }

        return self._guard(run)

    def habitat(self, habitat: str) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            rows = self.repository.assertions(habitat=habitat)
            definitions = self.repository.definitions(
                sorted({r["trait_id"] for r in rows})
            )
            return {
                "contract_version": CONTRACT_VERSION,
                "state": "AVAILABLE" if rows else "ABSENT",
                "habitat": habitat,
                "assertions": [
                    _public_assertion(r, definitions.get(r["trait_id"])) for r in rows
                ],
            }

        return self._guard(run)

    def conflicts(
        self, *, taxon_id: str | None = None, trait_id: str | None = None
    ) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            rows = self.repository.assertions(
                taxon_ids=[taxon_id] if taxon_id else None, trait_id=trait_id
            )
            found = projection.conflicts([row_to_assertion(r) for r in rows])
            return {
                "contract_version": CONTRACT_VERSION,
                "state": "AVAILABLE",
                "conflicts": found,
            }

        return self._guard(run)

    # ------------------------------------------------------- Calyx and Matrix
    def calyx(self, taxon_id: str, trait_id: str) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            definition = self.repository.definitions([trait_id]).get(trait_id)
            if definition is None or self._taxon(taxon_id) is None:
                return {
                    "contract_version": CONTRACT_VERSION,
                    "state": "UNKNOWN",
                    "taxon_id": taxon_id,
                    "trait_id": trait_id,
                }
            rows = self.repository.assertions(taxon_ids=[taxon_id], trait_id=trait_id)
            assertions = [row_to_assertion(r) for r in rows]
            relations = [
                row_to_relation(r) for r in self.repository.relations(trait_id)
            ]
            envelope = projection.calyx_envelope(
                definition, taxon_id, assertions, relations
            )
            requests, withheld = projection.candidate_handoff_requests(definition, rows)
            return {
                "state": "AVAILABLE" if rows else "ABSENT",
                **envelope,
                "candidate_handoff": {
                    "mode": "preview_only",
                    "requests": [r.model_dump(mode="json") for r in requests],
                    "withheld": withheld,
                },
            }

        return self._guard(run)

    def matrix(
        self, taxon_ids: list[str], trait_id: str | None = None
    ) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            rows = self.repository.assertions(taxon_ids=taxon_ids, trait_id=trait_id)
            assertions: list[AssertionIn] = [row_to_assertion(r) for r in rows]
            definitions = self.repository.definitions(
                sorted({a.trait_id for a in assertions})
            )
            labels = {
                t: c.name for t, c in self.repository.canonical_taxa(taxon_ids).items()
            }
            items = projection.matrix_assertions(definitions, assertions, labels)
            governed = [
                RelationshipAssertion(
                    **{k: v for k, v in item.items() if k not in projection.GOVERNANCE}
                )
                for item in items
            ]
            matrices = {
                dimension: build_relationship_matrix(
                    [g for g in governed if g.dimension == dimension],
                    dimension=dimension,
                    subject_ids=taxon_ids,
                )
                for dimension in sorted({g.dimension for g in governed})
            }
            return {
                "contract_version": CONTRACT_VERSION,
                "state": "AVAILABLE" if items else "ABSENT",
                "assertions": items,
                "matrices": matrices,
                **projection.GOVERNANCE,
            }

        return self._guard(run)
