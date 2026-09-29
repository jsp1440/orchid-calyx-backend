"""The locked taxonomy-reconciliation fixture used by CALYX-EVOLVE-001.

The fixture is a small, checked-in, deterministic reconciliation task with
explicit expected outcomes.  It is *not* production data and it is *not* the
Hassler acceptance corpus: it exists so candidate strategies can be compared
objectively without touching any production database, Knowledge Graph, or
taxonomy release.

Reference taxa follow the canonical World Plants shape already used by
``runtime.knowledge_graph.canonical_taxonomy``: an accepted name, optional
authorship, and synonyms that point at their accepted taxon.

Expected outcomes use two forms:

``accepted``
    The reconciler must emit this accepted name.
``unresolved``
    The reconciler must abstain.  Emitting any accepted name for such a record
    is a **false merge** — the failure class this fixture exists to expose.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from runtime.calyx_evolve.provenance import content_hash

FIXTURE_ID = "taxonomy-reconciliation-fixture-001"
FIXTURE_VERSION = "1.0.0"
RELEASE_ID = "world-plants-evolve-fixture-2026-08"
RELEASE_LABEL = "World Plants reconciliation fixture (synthetic, staging only)"

EXPECT_ACCEPTED = "accepted"
EXPECT_UNRESOLVED = "unresolved"

ACCEPTED = "accepted"
SYNONYM = "synonym"


@dataclass(frozen=True, slots=True)
class ReferenceTaxon:
    """One row of the locked reference release."""

    reference_id: str
    scientific_name: str
    authorship: str | None
    status: str
    accepted_reference_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference_id": self.reference_id,
            "scientific_name": self.scientific_name,
            "authorship": self.authorship,
            "status": self.status,
            "accepted_reference_id": self.accepted_reference_id,
        }


@dataclass(frozen=True, slots=True)
class FixtureRecord:
    """One input observation with its locked expected outcome."""

    record_id: str
    observed_name: str
    source_reference: str
    expected_outcome: str
    expected_accepted_name: str | None
    note: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "observed_name": self.observed_name,
            "source_reference": self.source_reference,
            "expected_outcome": self.expected_outcome,
            "expected_accepted_name": self.expected_accepted_name,
            "note": self.note,
        }


REFERENCE_TAXA: tuple[ReferenceTaxon, ...] = (
    ReferenceTaxon("ref-001", "Cattleya labiata", "Lindl.", ACCEPTED),
    ReferenceTaxon("ref-002", "Cattleya lobata", "Lindl.", ACCEPTED),
    ReferenceTaxon("ref-003", "Cattleya warneri", "T.Moore", ACCEPTED),
    ReferenceTaxon("ref-004", "Cattleya purpurata", "(Lindl. & Paxton) Van den Berg", ACCEPTED),
    ReferenceTaxon("ref-005", "Laelia purpurata", "Lindl. & Paxton", SYNONYM, "ref-004"),
    ReferenceTaxon("ref-006", "Epidendrum secundum", "Jacq.", ACCEPTED),
    ReferenceTaxon("ref-007", "Sobralia macrantha", "Lindl.", ACCEPTED),
    ReferenceTaxon("ref-008", "Phragmipedium besseae", "Dodson & J.Kuhn", ACCEPTED),
)

FIXTURE_RECORDS: tuple[FixtureRecord, ...] = (
    FixtureRecord(
        "rec-01",
        "Cattleya labiata",
        "fixture-sheet:1",
        EXPECT_ACCEPTED,
        "Cattleya labiata",
        "exact accepted name",
    ),
    FixtureRecord(
        "rec-02",
        "Cattleya labiata Lindl.",
        "fixture-sheet:2",
        EXPECT_ACCEPTED,
        "Cattleya labiata",
        "accepted name carrying authorship",
    ),
    FixtureRecord(
        "rec-03",
        "Laelia purpurata",
        "fixture-sheet:3",
        EXPECT_ACCEPTED,
        "Cattleya purpurata",
        "synonym that must be followed to its accepted taxon",
    ),
    FixtureRecord(
        "rec-04",
        "Laelia purpurata Lindl. & Paxton",
        "fixture-sheet:4",
        EXPECT_ACCEPTED,
        "Cattleya purpurata",
        "synonym carrying authorship",
    ),
    FixtureRecord(
        "rec-05",
        "cattleya warneri",
        "fixture-sheet:5",
        EXPECT_ACCEPTED,
        "Cattleya warneri",
        "lower-case genus",
    ),
    FixtureRecord(
        "rec-06",
        "Cattleya  warneri",
        "fixture-sheet:6",
        EXPECT_ACCEPTED,
        "Cattleya warneri",
        "doubled internal whitespace",
    ),
    FixtureRecord(
        "rec-07",
        "Epidendrum secundun",
        "fixture-sheet:7",
        EXPECT_ACCEPTED,
        "Epidendrum secundum",
        "single-character typo with exactly one near neighbour",
    ),
    FixtureRecord(
        "rec-08",
        "Cattleya lobata",
        "fixture-sheet:8",
        EXPECT_ACCEPTED,
        "Cattleya lobata",
        "accepted name confusable with Cattleya labiata",
    ),
    FixtureRecord(
        "rec-09",
        "Cattleya lobiata",
        "fixture-sheet:9",
        EXPECT_UNRESOLVED,
        None,
        "ambiguous: equidistant from Cattleya labiata and Cattleya lobata; "
        "resolving it is a false merge",
    ),
    FixtureRecord(
        "rec-10",
        "Sobralia macranta",
        "fixture-sheet:10",
        EXPECT_ACCEPTED,
        "Sobralia macrantha",
        "single-character typo with exactly one near neighbour",
    ),
    FixtureRecord(
        "rec-11",
        "Bulbophyllum nonexistente",
        "fixture-sheet:11",
        EXPECT_UNRESOLVED,
        None,
        "absent from the locked release; must abstain",
    ),
    FixtureRecord(
        "rec-12",
        "Phragmipedium besseae Dodson & J.Kuhn",
        "fixture-sheet:12",
        EXPECT_ACCEPTED,
        "Phragmipedium besseae",
        "accepted name carrying compound authorship",
    ),
)


@dataclass(frozen=True, slots=True)
class TaxonomyFixture:
    """An immutable reconciliation task with locked expectations."""

    fixture_id: str
    version: str
    release_id: str
    release_label: str
    reference_taxa: tuple[ReferenceTaxon, ...]
    records: tuple[FixtureRecord, ...]

    @property
    def release_checksum(self) -> str:
        return content_hash([taxon.to_dict() for taxon in self.reference_taxa])

    @property
    def fixture_hash(self) -> str:
        return content_hash(
            {
                "fixture_id": self.fixture_id,
                "version": self.version,
                "release_id": self.release_id,
                "release_checksum": self.release_checksum,
                "records": [record.to_dict() for record in self.records],
            }
        )

    def accepted_taxa(self) -> tuple[ReferenceTaxon, ...]:
        return tuple(t for t in self.reference_taxa if t.status == ACCEPTED)

    def by_reference_id(self, reference_id: str) -> ReferenceTaxon | None:
        for taxon in self.reference_taxa:
            if taxon.reference_id == reference_id:
                return taxon
        return None

    def expected_outcomes(self) -> dict[str, tuple[str, str | None]]:
        return {
            record.record_id: (record.expected_outcome, record.expected_accepted_name)
            for record in self.records
        }

    def descriptor(self) -> dict[str, Any]:
        """Concise, inspectable description used in durable records."""

        return {
            "fixture_id": self.fixture_id,
            "version": self.version,
            "release_id": self.release_id,
            "release_label": self.release_label,
            "release_checksum": self.release_checksum,
            "fixture_hash": self.fixture_hash,
            "reference_taxa": len(self.reference_taxa),
            "records": len(self.records),
        }


LOCKED_TAXONOMY_FIXTURE = TaxonomyFixture(
    fixture_id=FIXTURE_ID,
    version=FIXTURE_VERSION,
    release_id=RELEASE_ID,
    release_label=RELEASE_LABEL,
    reference_taxa=REFERENCE_TAXA,
    records=FIXTURE_RECORDS,
)


def locked_fixture() -> TaxonomyFixture:
    """Return the single locked reconciliation fixture for this phase."""

    return LOCKED_TAXONOMY_FIXTURE
