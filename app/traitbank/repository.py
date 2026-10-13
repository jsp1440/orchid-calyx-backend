"""PostgreSQL persistence for ``oc-traitbank-v1`` (``migrations/20261011_oc_traitbank_v1.sql``).

Writes happen only through :meth:`TraitBankRepository.ingest` and
:meth:`TraitBankRepository.load_definitions`, each one transaction:

- every guard and reference check runs before the first insert, and any
  violation refuses the whole batch;
- ``batch_key`` is the idempotency key: the same key with the same payload is a
  no-op, the same key with a different payload is refused;
- a source record (``source_id``, ``original_record_id``, ``trait_id``) is
  stored once: an identical resubmission is skipped, a different one is
  refused rather than overwriting what is stored;
- ``dry_run`` performs every check and rolls back.

Reads run in ``READ ONLY`` transactions.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from typing import Any

import psycopg
from psycopg.rows import dict_row, tuple_row
from psycopg.types.json import Jsonb

from . import guards
from .contract import BRAIN_CONTRACT_SHA256
from .models import (
    AssertionIn,
    EnvironmentRelationIn,
    TraitBankBatch,
    TraitDefinitionIn,
)
from .taxa import CanonicalTaxa, PostgresCanonicalTaxa

MAX_READ_ROWS = 5000
SUPERSESSION_KINDS = (
    "corrected",
    "reidentified",
    "reanalysed",
    "duplicate_of",
    "retracted",
)
SOURCE_RECORD_KINDS = ("measurement", "claim", "dataset_record", "curated")


class TraitBankRefused(ValueError):
    """A batch or definition was refused. ``violations`` lists every reason."""

    def __init__(self, violations: list[dict[str, str]]):
        self.violations = violations
        super().__init__("; ".join(f"{v['code']}@{v['where']}" for v in violations))


class ResultTooLarge(RuntimeError):
    """A read matched more rows than the cap.

    Summaries, conflicts, Calyx envelopes and matrices are computed over the
    whole result, so a silently truncated read would present partial evidence
    as complete (and could drop one side of a conflict). Callers fail closed.
    """


def _within_cap(rows: list[dict[str, Any]], cap: int) -> list[dict[str, Any]]:
    if len(rows) > cap:
        raise ResultTooLarge(cap)
    return rows


def _sha256(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def record_sha256(
    model: AssertionIn | EnvironmentRelationIn | TraitDefinitionIn,
) -> str:
    return _sha256(model.model_dump(mode="json"))


def default_crosswalk(producer: str, a: AssertionIn) -> dict[str, Any]:
    """Crosswalk entry when the producer supplied none. Never guesses a KG key."""
    kind = {"eol_traitbank": "dataset_record", "curated": "curated"}.get(producer)
    if kind is None:  # literature without an adapter-supplied crosswalk
        kind = "measurement" if a.value.kind in ("quantitative", "range") else "claim"
    return {
        "source_record_kind": kind,
        "kg_object_key": None,
        "source_document_id": a.provenance.source_id,
    }


def _v(code: str, where: str) -> dict[str, str]:
    return {"code": code, "where": where}


_ASSERTION_COLUMNS = (
    "assertion_id",
    "batch_pk",
    "trait_id",
    "level",
    "taxon_id",
    "verbatim_taxon_name",
    "specimen_id",
    "population_id",
    "observation_id",
    "value_kind",
    "numeric_value",
    "minimum_value",
    "maximum_value",
    "unit",
    "state_id",
    "statistic",
    "sd",
    "sample_size",
    "uncertainty",
    "missing_reason",
    "verbatim_value",
    "evidence_state",
    "scope_basis",
    "scope_justification",
    "derived_from",
    "method_id",
    "confidence",
    "life_stage",
    "habitats",
    "links",
    "notes",
    "source_id",
    "source_kind",
    "original_record_id",
    "citation",
    "license",
    "evidence_type",
    "contributor",
    "source_url",
    "locator",
    "original_text",
    "retrieved_at",
    "extraction_method",
    "review_status",
    "record_sha256",
)


def row_to_assertion(row: dict[str, Any]) -> AssertionIn:
    """Rebuild the contract record from a stored row (round-trips exactly)."""
    return AssertionIn.model_validate(
        {
            "assertion_id": row["assertion_id"],
            "trait_id": row["trait_id"],
            "level": row["level"],
            "subject": {
                "taxon_id": str(row["taxon_id"]),
                "verbatim_taxon_name": row["verbatim_taxon_name"],
                "specimen_id": row["specimen_id"],
                "population_id": row["population_id"],
                "observation_id": row["observation_id"],
            },
            "value": {
                "kind": row["value_kind"],
                "numeric": row["numeric_value"],
                "minimum": row["minimum_value"],
                "maximum": row["maximum_value"],
                "unit": row["unit"],
                "state_id": row["state_id"],
                "statistic": row["statistic"],
                "sd": row["sd"],
                "n": row["sample_size"],
                "uncertainty": row["uncertainty"],
                "missing_reason": row["missing_reason"],
                "verbatim": row["verbatim_value"],
            },
            "provenance": {
                k: row[k]
                for k in (
                    "source_id",
                    "source_kind",
                    "original_record_id",
                    "citation",
                    "license",
                    "evidence_type",
                    "contributor",
                    "source_url",
                    "locator",
                    "original_text",
                    "retrieved_at",
                    "extraction_method",
                    "review_status",
                )
            },
            "evidence_state": row["evidence_state"],
            "scope_basis": row["scope_basis"],
            "scope_justification": row["scope_justification"],
            "derived_from": tuple(row["derived_from"] or ()),
            "method_id": row["method_id"],
            "confidence": float(row["confidence"])
            if row["confidence"] is not None
            else None,
            "life_stage": row["life_stage"],
            "habitats": tuple(row["habitats"] or ()),
            "links": tuple(row["links"] or ()),
            "notes": row["notes"],
        }
    )


def row_to_relation(row: dict[str, Any]) -> EnvironmentRelationIn:
    return EnvironmentRelationIn.model_validate(
        {
            "relation_id": row["relation_id"],
            "trait_id": row["trait_id"],
            "environment_variable": row["environment_variable"],
            "claim_kind": row["claim_kind"],
            "statement": row["statement"],
            "taxon_scope": tuple(str(t) for t in row["taxon_scope"] or ()),
            "direction": row["direction"],
            "effect_size": row["effect_size"],
            "n": row["sample_size"],
            "hypothesis_scope": row["hypothesis_scope"],
            "test_design": row["test_design"],
            "test_outcome": row["test_outcome"],
            "provenance": row["provenance"],
        }
    )


class TraitBankRepository:
    def __init__(
        self,
        database_url: str | None = None,
        *,
        connection_factory: Callable[..., Any] | None = None,
        taxa: CanonicalTaxa | None = None,
    ) -> None:
        # The dedicated variable only: a generic DATABASE_URL may name an
        # unrelated (production) database, matching the CLI's rule.
        self.database_url = database_url or os.getenv("TRAITBANK_DATABASE_URL")
        self.connection_factory = connection_factory or psycopg.connect
        self.taxa = taxa or PostgresCanonicalTaxa()

    def _connect(self):
        if not self.database_url:
            raise RuntimeError("TRAITBANK_DATABASE_URL is required for TraitBank")
        return self.connection_factory(self.database_url, row_factory=dict_row)

    # ------------------------------------------------------------ definitions
    def load_definitions(
        self, definitions: list[TraitDefinitionIn], *, live: bool = True
    ) -> dict[str, Any]:
        violations = [
            v.as_dict()
            for d in definitions
            for v in guards.check_definition(d, live=live)
        ]
        if violations:
            raise TraitBankRefused(violations)
        inserted, unchanged = [], []
        with self._connect() as conn, conn.transaction():
            for d in definitions:
                digest = record_sha256(d)
                existing = conn.execute(
                    "SELECT definition_sha256 FROM oc_traitbank.trait_definitions WHERE trait_id = %s",
                    (d.trait_id,),
                ).fetchone()
                if existing:
                    if existing["definition_sha256"] != digest:
                        raise TraitBankRefused(
                            [_v("DEFINITION_CHANGED_REQUIRES_NEW_TRAIT_ID", d.trait_id)]
                        )
                    unchanged.append(d.trait_id)
                    continue
                conn.execute(
                    "INSERT INTO oc_traitbank.trait_definitions (trait_id, label, domain, structure, property, "
                    "value_kind, unit, oao_character_id, definition, definition_sha256, brain_contract_sha256) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        d.trait_id,
                        d.label,
                        d.domain,
                        d.structure,
                        d.property,
                        d.value_kind,
                        d.unit,
                        d.oao_character_id,
                        Jsonb(d.model_dump(mode="json")),
                        digest,
                        BRAIN_CONTRACT_SHA256,
                    ),
                )
                inserted.append(d.trait_id)
        return {"inserted": inserted, "unchanged": unchanged}

    @staticmethod
    def _definitions(
        conn: Any, trait_ids: list[str] | None = None
    ) -> dict[str, TraitDefinitionIn]:
        if trait_ids is None:
            rows = conn.execute(
                "SELECT definition FROM oc_traitbank.trait_definitions ORDER BY trait_id"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT definition FROM oc_traitbank.trait_definitions WHERE trait_id = ANY(%s)",
                (trait_ids,),
            ).fetchall()
        return {
            r["definition"]["trait_id"]: TraitDefinitionIn.model_validate(
                r["definition"]
            )
            for r in rows
        }

    # ---------------------------------------------------------------- ingest
    def _reference_checks(
        self, conn: Any, batch: TraitBankBatch
    ) -> list[dict[str, str]]:
        violations: list[dict[str, str]] = []
        trait_ids = sorted(
            {a.trait_id for a in batch.assertions}
            | {r.trait_id for r in batch.environment_relations}
        )
        definitions = self._definitions(conn, trait_ids)
        taxon_ids = sorted(
            {a.subject.taxon_id for a in batch.assertions}
            | {t for r in batch.environment_relations for t in r.taxon_scope}
        )
        with conn.cursor(row_factory=tuple_row) as cur:
            canonical = self.taxa.get_many(cur, taxon_ids) if taxon_ids else {}
        for taxon_id in taxon_ids:
            if taxon_id not in canonical:
                violations.append(
                    _v("TAXON_NOT_IN_CANONICAL_TAXONOMY", f"taxon:{taxon_id}")
                )
        batch_ids = {a.assertion_id for a in batch.assertions}
        stored_parents: set[str] = set()
        parents = sorted(
            {p for a in batch.assertions for p in a.derived_from} - batch_ids
        )
        if parents:
            stored_parents = {
                r["assertion_id"]
                for r in conn.execute(
                    "SELECT assertion_id FROM oc_traitbank.assertions WHERE assertion_id = ANY(%s)",
                    (parents,),
                ).fetchall()
            }
        for a in batch.assertions:
            where = f"assertion:{a.assertion_id}"
            d = definitions.get(a.trait_id)
            if d is None:
                violations.append(_v("UNKNOWN_TRAIT_ID", where))
                continue
            kind = a.value.kind
            if kind in ("quantitative", "range"):
                if d.value_kind != "quantitative":
                    violations.append(_v("VALUE_KIND_MISMATCH", where))
                elif a.value.unit != d.unit:
                    violations.append(_v("UNIT_NOT_CANONICAL", where))
            if kind == "categorical" and (
                d.value_kind != "categorical" or d.state(a.value.state_id or "") is None
            ):
                violations.append(_v("UNKNOWN_STATE_FOR_TRAIT", where))
            if a.method_id and a.method_id not in {m.method_id for m in d.methods}:
                violations.append(_v("UNKNOWN_METHOD_FOR_TRAIT", where))
            for parent in a.derived_from:
                if parent not in batch_ids and parent not in stored_parents:
                    violations.append(_v("DERIVED_FROM_UNKNOWN_ASSERTION", where))
        for r in batch.environment_relations:
            if r.trait_id not in definitions:
                violations.append(_v("UNKNOWN_TRAIT_ID", f"relation:{r.relation_id}"))
        return violations

    def ingest(
        self,
        batch: TraitBankBatch,
        *,
        ingested_by: str,
        live: bool = True,
        dry_run: bool = False,
        crosswalk: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if not ingested_by.strip():
            raise TraitBankRefused([_v("INGESTED_BY_REQUIRED", "ingested_by")])
        crosswalk = dict(crosswalk or {})
        unknown = sorted(set(crosswalk) - {a.assertion_id for a in batch.assertions})
        if unknown:
            raise TraitBankRefused(
                [
                    _v("CROSSWALK_NAMES_UNKNOWN_ASSERTION", f"assertion:{i}")
                    for i in unknown
                ]
            )
        for assertion_id, entry in crosswalk.items():
            if entry.get("source_record_kind") not in SOURCE_RECORD_KINDS:
                raise TraitBankRefused(
                    [_v("CROSSWALK_KIND_INVALID", f"assertion:{assertion_id}")]
                )
        violations = [v.as_dict() for v in guards.check_batch(batch, live=live)]
        if violations:
            raise TraitBankRefused(violations)
        payload_sha = _sha256(batch.model_dump(mode="json"))
        report: dict[str, Any] = {
            "batch_key": batch.batch_key,
            "payload_sha256": payload_sha,
            "dry_run": dry_run,
            "inserted_assertions": [],
            "skipped_identical_assertions": [],
            "inserted_relations": [],
            "skipped_identical_relations": [],
        }
        with self._connect() as conn, conn.transaction() as tx:
            # Serialise concurrent submissions of the same batch key.
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"traitbank:{batch.batch_key}",),
            )
            prior = conn.execute(
                "SELECT batch_pk, payload_sha256 FROM oc_traitbank.ingestion_batches WHERE batch_key = %s",
                (batch.batch_key,),
            ).fetchone()
            if prior:
                if prior["payload_sha256"] != payload_sha:
                    raise TraitBankRefused(
                        [_v("BATCH_KEY_REUSED_WITH_DIFFERENT_PAYLOAD", batch.batch_key)]
                    )
                return {
                    **report,
                    "state": "ALREADY_INGESTED",
                    "batch_pk": prior["batch_pk"],
                }

            violations = self._reference_checks(conn, batch)
            pending_assertions: list[tuple[AssertionIn, str]] = []
            for a in batch.assertions:
                digest = record_sha256(a)
                stored = conn.execute(
                    "SELECT assertion_id, record_sha256 FROM oc_traitbank.assertions "
                    "WHERE assertion_id = %s OR (source_id = %s AND original_record_id = %s AND trait_id = %s)",
                    (
                        a.assertion_id,
                        a.provenance.source_id,
                        a.provenance.original_record_id,
                        a.trait_id,
                    ),
                ).fetchall()
                if not stored:
                    pending_assertions.append((a, digest))
                elif (
                    len(stored) == 1
                    and stored[0]["record_sha256"] == digest
                    and stored[0]["assertion_id"] == a.assertion_id
                ):
                    report["skipped_identical_assertions"].append(a.assertion_id)
                else:
                    violations.append(
                        _v(
                            "SOURCE_RECORD_CONFLICTS_WITH_STORED_ASSERTION",
                            f"assertion:{a.assertion_id}",
                        )
                    )
            pending_relations: list[tuple[EnvironmentRelationIn, str]] = []
            for r in batch.environment_relations:
                digest = record_sha256(r)
                stored = conn.execute(
                    "SELECT record_sha256 FROM oc_traitbank.environment_relations WHERE relation_id = %s",
                    (r.relation_id,),
                ).fetchone()
                if stored is None:
                    pending_relations.append((r, digest))
                elif stored["record_sha256"] == digest:
                    report["skipped_identical_relations"].append(r.relation_id)
                else:
                    violations.append(
                        _v(
                            "RELATION_CONFLICTS_WITH_STORED",
                            f"relation:{r.relation_id}",
                        )
                    )
            if violations:
                raise TraitBankRefused(violations)

            batch_pk = conn.execute(
                "INSERT INTO oc_traitbank.ingestion_batches (batch_key, payload_sha256, producer, contract_version, "
                "brain_contract_sha256, assertion_count, relation_count, ingested_by) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING batch_pk",
                (
                    batch.batch_key,
                    payload_sha,
                    batch.producer,
                    batch.contract_version,
                    BRAIN_CONTRACT_SHA256,
                    len(pending_assertions),
                    len(pending_relations),
                    ingested_by,
                ),
            ).fetchone()["batch_pk"]
            placeholders = ",".join(["%s"] * len(_ASSERTION_COLUMNS))
            insert_sql = f"INSERT INTO oc_traitbank.assertions ({', '.join(_ASSERTION_COLUMNS)}) VALUES ({placeholders})"
            for a, digest in pending_assertions:
                val, prov, sub = a.value, a.provenance, a.subject
                conn.execute(
                    insert_sql,
                    (
                        a.assertion_id,
                        batch_pk,
                        a.trait_id,
                        a.level,
                        int(sub.taxon_id),
                        sub.verbatim_taxon_name,
                        sub.specimen_id,
                        sub.population_id,
                        sub.observation_id,
                        val.kind,
                        val.numeric,
                        val.minimum,
                        val.maximum,
                        val.unit,
                        val.state_id,
                        val.statistic,
                        val.sd,
                        val.n,
                        val.uncertainty,
                        val.missing_reason,
                        val.verbatim,
                        a.evidence_state,
                        a.scope_basis,
                        a.scope_justification,
                        list(a.derived_from),
                        a.method_id,
                        a.confidence,
                        a.life_stage,
                        list(a.habitats),
                        Jsonb([link.model_dump(mode="json") for link in a.links]),
                        a.notes,
                        prov.source_id,
                        prov.source_kind,
                        prov.original_record_id,
                        prov.citation,
                        prov.license,
                        prov.evidence_type,
                        prov.contributor,
                        prov.source_url,
                        prov.locator,
                        prov.original_text,
                        prov.retrieved_at,
                        prov.extraction_method,
                        prov.review_status,
                        digest,
                    ),
                )
                report["inserted_assertions"].append(a.assertion_id)
                entry = crosswalk.get(a.assertion_id) or default_crosswalk(
                    batch.producer, a
                )
                conn.execute(
                    "INSERT INTO oc_traitbank.evidence_crosswalk "
                    "(assertion_id, source_record_kind, kg_object_key, source_document_id) "
                    "VALUES (%s,%s,%s,%s)",
                    (
                        a.assertion_id,
                        entry["source_record_kind"],
                        entry.get("kg_object_key"),
                        entry.get("source_document_id") or prov.source_id,
                    ),
                )
            for r, digest in pending_relations:
                p = r.provenance
                conn.execute(
                    "INSERT INTO oc_traitbank.environment_relations (relation_id, batch_pk, trait_id, "
                    "environment_variable, claim_kind, statement, taxon_scope, direction, effect_size, sample_size, "
                    "hypothesis_scope, test_design, test_outcome, source_id, original_record_id, citation, license, "
                    "evidence_type, locator, original_text, provenance, record_sha256) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        r.relation_id,
                        batch_pk,
                        r.trait_id,
                        r.environment_variable,
                        r.claim_kind,
                        r.statement,
                        [int(t) for t in r.taxon_scope],
                        r.direction,
                        r.effect_size,
                        r.n,
                        r.hypothesis_scope,
                        r.test_design,
                        r.test_outcome,
                        p.source_id,
                        p.original_record_id,
                        p.citation,
                        p.license,
                        p.evidence_type,
                        p.locator,
                        p.original_text,
                        Jsonb(p.model_dump(mode="json")),
                        digest,
                    ),
                )
                report["inserted_relations"].append(r.relation_id)
            report.update(
                state="DRY_RUN_OK" if dry_run else "INGESTED", batch_pk=batch_pk
            )
            if dry_run:
                # Every check ran against the live state; nothing is kept.
                raise psycopg.Rollback(tx)
        return report

    # ------------------------------------------------------------------ reads
    def _read(self, query: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        with self._connect() as conn, conn.transaction():
            conn.execute("SET TRANSACTION READ ONLY")
            return conn.execute(query, params).fetchall()

    def definitions(
        self, trait_ids: list[str] | None = None
    ) -> dict[str, TraitDefinitionIn]:
        with self._connect() as conn, conn.transaction():
            conn.execute("SET TRANSACTION READ ONLY")
            return self._definitions(conn, trait_ids)

    def assertions(
        self,
        *,
        taxon_ids: list[str] | None = None,
        trait_id: str | None = None,
        source_id: str | None = None,
        assertion_id: str | None = None,
        habitat: str | None = None,
        current_only: bool = False,
        limit: int = MAX_READ_ROWS,
    ) -> list[dict[str, Any]]:
        """Stored assertions with their supersession and crosswalk, never rewritten.

        ``current_only`` drops assertions that a later decision superseded or
        retracted; the stored rows themselves are unchanged either way.
        """
        conditions, params = [], []
        if current_only:
            conditions.append("s.superseded_assertion_id IS NULL")
        if taxon_ids is not None:
            conditions.append("a.taxon_id = ANY(%s)")
            params.append([int(t) for t in taxon_ids])
        if trait_id:
            conditions.append("a.trait_id = %s")
            params.append(trait_id)
        if source_id:
            conditions.append("a.source_id = %s")
            params.append(source_id)
        if assertion_id:
            conditions.append("a.assertion_id = %s")
            params.append(assertion_id)
        if habitat:
            conditions.append(
                "(lower(%s) = ANY(SELECT lower(h) FROM unnest(a.habitats) h) OR EXISTS ("
                "SELECT 1 FROM jsonb_array_elements(a.links) l WHERE l->>'domain' = 'habitat' "
                "AND lower(l->>'target_label') = lower(%s)))"
            )
            params.extend([habitat, habitat])
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        cap = min(max(limit, 1), MAX_READ_ROWS)
        params.append(cap + 1)
        return _within_cap(
            self._read(
                f"SELECT a.*, b.batch_key, b.producer, "
                f"s.superseding_assertion_id AS superseded_by, s.kind AS supersession_kind, "
                f"s.reason AS supersession_reason, s.review_reference AS supersession_review_reference, "
                f"s.decided_by AS supersession_decided_by, s.created_at AS superseded_at, "
                f"c.source_record_kind, c.kg_object_key, c.source_document_id "
                f"FROM oc_traitbank.assertions a "
                f"JOIN oc_traitbank.ingestion_batches b USING (batch_pk) "
                f"LEFT JOIN oc_traitbank.assertion_supersessions s ON s.superseded_assertion_id = a.assertion_id "
                f"LEFT JOIN oc_traitbank.evidence_crosswalk c ON c.assertion_id = a.assertion_id {where} "
                f"ORDER BY a.taxon_id, a.trait_id, a.assertion_id LIMIT %s",
                tuple(params),
            ),
            cap,
        )

    def relations(self, trait_id: str) -> list[dict[str, Any]]:
        return _within_cap(
            self._read(
                "SELECT * FROM oc_traitbank.environment_relations WHERE trait_id = %s ORDER BY relation_id LIMIT %s",
                (trait_id, MAX_READ_ROWS + 1),
            ),
            MAX_READ_ROWS,
        )

    def canonical_taxa(self, taxon_ids: list[str]) -> dict[str, Any]:
        with self._connect() as conn, conn.transaction():
            conn.execute("SET TRANSACTION READ ONLY")
            with conn.cursor(row_factory=tuple_row) as cur:
                return self.taxa.get_many(cur, taxon_ids)

    def resolve_species(self, name: str) -> str | None:
        with self._connect() as conn, conn.transaction():
            conn.execute("SET TRANSACTION READ ONLY")
            with conn.cursor(row_factory=tuple_row) as cur:
                return self.taxa.resolve_species(cur, name)

    def taxon_graph_nodes(self, taxon_ids: list[str]) -> dict[str, Any] | None:
        from .interop import taxon_graph_nodes

        with self._connect() as conn, conn.transaction():
            conn.execute("SET TRANSACTION READ ONLY")
            with conn.cursor(row_factory=tuple_row) as cur:
                return taxon_graph_nodes(cur, taxon_ids)

    def genus_ids(self, genus: str) -> list[str]:
        with self._connect() as conn, conn.transaction():
            conn.execute("SET TRANSACTION READ ONLY")
            with conn.cursor(row_factory=tuple_row) as cur:
                return self.taxa.genus_ids(cur, genus)

    # ------------------------------------------------------------ supersession
    def supersede(
        self,
        *,
        superseded_assertion_id: str,
        superseding_assertion_id: str | None,
        kind: str,
        reason: str,
        review_reference: str,
        decided_by: str,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Record that a stored assertion is no longer current. Never edits it.

        The original keeps its value, citation, level and evidence state; this
        writes one append-only decision row naming why, who decided, under
        which review, and (unless retracted) which stored assertion replaces it.
        """
        violations: list[dict[str, str]] = []
        if kind not in SUPERSESSION_KINDS:
            violations.append(_v("SUPERSESSION_KIND_INVALID", kind))
        if len(reason.strip()) < 10:
            violations.append(_v("SUPERSESSION_REASON_REQUIRED", "reason"))
        if not review_reference.strip():
            violations.append(_v("REVIEW_REFERENCE_REQUIRED", "review_reference"))
        if not decided_by.strip():
            violations.append(_v("DECIDED_BY_REQUIRED", "decided_by"))
        if kind == "retracted" and superseding_assertion_id:
            violations.append(
                _v("RETRACTION_HAS_NO_SUCCESSOR", "superseding_assertion_id")
            )
        if kind != "retracted" and not superseding_assertion_id:
            violations.append(_v("SUCCESSOR_REQUIRED", "superseding_assertion_id"))
        if superseding_assertion_id == superseded_assertion_id:
            violations.append(_v("SUPERSESSION_NOT_SELF", superseded_assertion_id))
        for field, text in (("reason", reason), ("review_reference", review_reference)):
            violations += [
                v.as_dict()
                for v in guards.privacy_violations(f"supersession.{field}", text)
            ]
        if violations:
            raise TraitBankRefused(violations)
        record = {
            "superseded_assertion_id": superseded_assertion_id,
            "superseding_assertion_id": superseding_assertion_id,
            "kind": kind,
            "reason": reason.strip(),
            "review_reference": review_reference.strip(),
            "decided_by": decided_by.strip(),
        }
        digest = _sha256(record)
        with self._connect() as conn, conn.transaction() as tx:
            # One decision per original at a time, and successor checks run
            # against the state this transaction will commit on top of.
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"traitbank:supersede:{superseded_assertion_id}",),
            )
            ids = [superseded_assertion_id] + (
                [superseding_assertion_id] if superseding_assertion_id else []
            )
            rows = {
                r["assertion_id"]: r
                for r in conn.execute(
                    "SELECT a.assertion_id, a.trait_id, a.taxon_id, s.superseding_assertion_id, "
                    "s.superseded_assertion_id IS NOT NULL AS is_superseded, s.record_sha256 "
                    "FROM oc_traitbank.assertions a LEFT JOIN oc_traitbank.assertion_supersessions s "
                    "ON s.superseded_assertion_id = a.assertion_id WHERE a.assertion_id = ANY(%s)",
                    (ids,),
                ).fetchall()
            }
            original = rows.get(superseded_assertion_id)
            if original is None:
                raise TraitBankRefused(
                    [_v("UNKNOWN_ASSERTION", superseded_assertion_id)]
                )
            if original["is_superseded"]:
                if original["record_sha256"] == digest:
                    return {
                        **record,
                        "state": "ALREADY_RECORDED",
                        "record_sha256": digest,
                    }
                raise TraitBankRefused(
                    [_v("ALREADY_SUPERSEDED", superseded_assertion_id)]
                )
            if superseding_assertion_id:
                successor = rows.get(superseding_assertion_id)
                if successor is None:
                    violations.append(_v("UNKNOWN_SUCCESSOR", superseding_assertion_id))
                else:
                    if successor["is_superseded"]:
                        violations.append(
                            _v("SUCCESSOR_NOT_CURRENT", superseding_assertion_id)
                        )
                    if successor["trait_id"] != original["trait_id"]:
                        violations.append(
                            _v("SUCCESSOR_TRAIT_MISMATCH", superseding_assertion_id)
                        )
                    taxon_changed = successor["taxon_id"] != original["taxon_id"]
                    # Only a re-identification may move evidence to another
                    # taxon, and a re-identification must actually move it.
                    if taxon_changed and kind != "reidentified":
                        violations.append(
                            _v(
                                "TAXON_CHANGE_REQUIRES_REIDENTIFIED",
                                superseding_assertion_id,
                            )
                        )
                    if kind == "reidentified" and not taxon_changed:
                        violations.append(
                            _v(
                                "REIDENTIFIED_REQUIRES_TAXON_CHANGE",
                                superseding_assertion_id,
                            )
                        )
            if violations:
                raise TraitBankRefused(violations)
            conn.execute(
                "INSERT INTO oc_traitbank.assertion_supersessions (superseded_assertion_id, "
                "superseding_assertion_id, kind, reason, review_reference, decided_by, record_sha256) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (
                    superseded_assertion_id,
                    superseding_assertion_id,
                    kind,
                    record["reason"],
                    record["review_reference"],
                    record["decided_by"],
                    digest,
                ),
            )
            result = {
                **record,
                "state": "DRY_RUN_OK" if dry_run else "RECORDED",
                "record_sha256": digest,
            }
            if dry_run:
                raise psycopg.Rollback(tx)
        return result

    def supersession_history(self, assertion_id: str) -> list[dict[str, Any]]:
        """The full linear chain this assertion belongs to, oldest first."""
        rows = _within_cap(
            self._read(
                "SELECT superseded_assertion_id, superseding_assertion_id, kind, reason, "
                "review_reference, decided_by, created_at FROM oc_traitbank.assertion_supersessions "
                "LIMIT %s",
                (MAX_READ_ROWS + 1,),
            ),
            MAX_READ_ROWS,
        )
        forward = {r["superseded_assertion_id"]: r for r in rows}
        backward = {
            r["superseding_assertion_id"]: r
            for r in rows
            if r["superseding_assertion_id"]
        }
        head = assertion_id
        seen = {head}
        while (
            head in backward and backward[head]["superseded_assertion_id"] not in seen
        ):
            head = backward[head]["superseded_assertion_id"]
            seen.add(head)
        chain, cursor, visited = [], head, set()
        while cursor in forward and cursor not in visited:
            visited.add(cursor)
            decision = forward[cursor]
            chain.append({**decision, "created_at": decision["created_at"].isoformat()})
            cursor = decision["superseding_assertion_id"]
        return chain
