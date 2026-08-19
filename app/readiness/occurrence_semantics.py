"""What counts as an orchid occurrence, and what does not.

The Orchid Continuum definition, encoded:

    An occurrence is evidence that an orchid taxon occurred at a particular
    place -- a legitimate observation, specimen, collection, or equivalent
    occurrence record.

``public.records`` is a universal ingest spine, not an occurrence table. It
holds explicitly-typed occurrence rows alongside vendor listings, videos, taxon
profiles and media. Measuring it whole would report a vendor listing as evidence
that an orchid grew somewhere, which is a fabrication with a row count attached.

Three rules govern this module.

**Classification is by semantics, never by shape.** A record does not become an
occurrence because it carries coordinates, an elevation, a GBIF key, or a
taxon name. Vendor listings carry all four. What makes an occurrence is that the
record *asserts a taxon was present at a place* -- so the record's own declared
type is the evidence, and everything else is corroboration.

**Unknown types are never admitted.** A record_type this module has not
classified is ``AMBIGUOUS``, and ambiguous never counts as an occurrence. New
ingest types therefore cannot silently inflate an occurrence metric by appearing;
they show up as unclassified and wait for a decision. Fail closed.

**Raw source data is never rewritten.** This is a derived classification applied
at read time. ``public.records`` keeps every row it harvested, including the
vendor listings; provenance columns (``source``, ``source_record_id``,
``gbif_occurrence_key``, ``record_type``) travel with every measurement.
"""

from __future__ import annotations

from typing import Any

OCCURRENCE = "occurrence"
NON_OCCURRENCE = "non-occurrence"
AMBIGUOUS = "ambiguous-requires-curation"

# Record types that ARE occurrence evidence, each with the reason it qualifies.
# Membership here is a scientific claim, so each entry carries one.
OCCURRENCE_TYPES: dict[str, str] = {
    "occurrence": (
        "Explicitly typed occurrence record: a taxon asserted present at a place."
    ),
    "observation": (
        "A field observation of a taxon at a place. The canonical Darwin Core "
        "HumanObservation basis of record."
    ),
    "HUMAN_OBSERVATION": (
        "Darwin Core basisOfRecord spelling of the same thing as 'observation'. "
        "Kept distinct because the vocabulary is not normalised upstream."
    ),
    "OBSERVATION": (
        "Third spelling of the same concept present in this corpus. Same "
        "semantics; the casing difference is an ingest artefact, not a "
        "distinction in the evidence."
    ),
    "specimen": (
        "A physical specimen collected at a place. The strongest form of "
        "occurrence evidence, and the basis of most herbarium records."
    ),
    "PRESERVED_SPECIMEN": (
        "Darwin Core basisOfRecord spelling of 'specimen': a preserved physical "
        "specimen with a collection locality."
    ),
    "MATERIAL_SAMPLE": (
        "A material sample taken from an organism at a place; occurrence "
        "evidence under Darwin Core."
    ),
    "MATERIAL_CITATION": (
        "A specimen citation in literature that records collection at a place."
    ),
    "LIVING_SPECIMEN": (
        "A living accession with collection locality. Occurrence evidence when "
        "the record carries the wild provenance rather than only cultivation."
    ),
    "MACHINE_OBSERVATION": (
        "An automated observation of a taxon at a place; occurrence evidence "
        "under Darwin Core."
    ),
    "collection": (
        "A collection event: a taxon gathered at a particular place on a "
        "particular date. Occurrence evidence by definition."
    ),
    "herbarium_specimen": (
        "A herbarium sheet: a pressed specimen collected at a place. The oldest "
        "and most durable form of occurrence evidence in botany."
    ),
    "species_observation": (
        "An observation of a species at a place; the same evidence as "
        "'observation' under a longer name."
    ),
}

# Record types that are NOT occurrence evidence, each with the reason.
NON_OCCURRENCE_TYPES: dict[str, str] = {
    "vendor_listing": (
        "Commercial availability of a plant for sale. Says nothing about where "
        "the taxon occurs in the world; a nursery's location is not a locality."
    ),
    "video": (
        "A video asset. Taxon and location metadata describe the FILE, not a "
        "documented occurrence of the organism."
    ),
    "taxon_profile": "A description of a taxon. Not tied to a place at all.",
    "species_profile": (
        "As taxon_profile: a synthesised description of a species, not a record "
        "of it being observed anywhere."
    ),
    "media_record": (
        "A media asset. Media may accompany an occurrence, but a media row is "
        "not itself the occurrence and counting it double-counts."
    ),
    "media_observation": (
        "A media asset attached to an observation. The observation is the "
        "occurrence; this row is its illustration."
    ),
    "occurrence_photo": (
        "A photograph attached to an occurrence. Same reasoning: the occurrence "
        "it depicts is already counted, and counting the photo inflates."
    ),
    "observation_photo": (
        "A photograph attached to an observation. The observation it illustrates "
        "is the occurrence and is already counted."
    ),
    "image": (
        "A bare image asset. An image of an orchid is not evidence of where the "
        "orchid grew unless an occurrence record says so."
    ),
    "photo": (
        "A bare photo asset; same reasoning as image. Depicting a taxon is not "
        "asserting where it occurred."
    ),
    "conservation_assessment": (
        "An assessment of a taxon's conservation status. A judgement about a "
        "taxon, not a record of it being somewhere."
    ),
    "literature": (
        "A literature record. Publications may REPORT occurrences, but the "
        "publication row is a bibliographic record; the occurrence must be "
        "extracted and typed as one to count."
    ),
    "publication": (
        "As literature: a bibliographic record. What it reports may be an "
        "occurrence; the publication row itself is not one."
    ),
    "trait": (
        "A trait assertion about a taxon, such as flower colour or growth habit. "
        "A property of the organism, not a place it was found."
    ),
    "glossary_term": (
        "A controlled-vocabulary entry. Carries no organism and no locality."
    ),
    "species_photo": (
        "A photograph of a species. Depicts the organism, not a documented "
        "instance of it growing somewhere."
    ),
    "hybrid_photo": "A photograph of a hybrid; see species_photo.",
    "photo_gallery": (
        "A gallery grouping of photographs. A container of media, further from "
        "occurrence evidence than the media itself."
    ),
    "photo_directory": "A directory of photographs; a media container.",
    "image_collection": "A collection of images; a media container.",
    "taxonomy_record": (
        "A taxonomic name record. Establishes what a taxon IS, not where it "
        "has been found."
    ),
    "genus_profile": "A description of a genus. Not tied to any place.",
    "cultivar": (
        "A named cultivar. A horticultural selection, whose existence says "
        "nothing about wild occurrence."
    ),
    "hybrid_registration": (
        "A registered grex or hybrid. A nomenclatural act in horticulture, not "
        "a field record."
    ),
    "vip_hybrid": "A featured hybrid entry; horticultural, not a field record.",
    "personal_collection": (
        "A plant held in a private collection. Records what someone grows, not "
        "where the taxon occurs in the wild."
    ),
    "personal_collection_hybrid": (
        "A hybrid held in a private collection; horticultural holding, not a "
        "wild occurrence."
    ),
    "living_collection": (
        "A living accession in a collection. Cultivated presence is not wild "
        "occurrence unless the record carries documented wild provenance, which "
        "this type does not assert."
    ),
    "breeder_catalog": (
        "A breeder's catalogue entry. Commercial availability, like "
        "vendor_listing."
    ),
    "hybrid_listing": "A hybrid offered commercially; see vendor_listing.",
    "culture_sheet": (
        "Cultivation guidance for growing a taxon. Advice, not a field record."
    ),
    "judging_standard": (
        "A show-judging standard. A horticultural convention about how a plant "
        "should look."
    ),
    "knowledge_article": "An explanatory article. Editorial content.",
    "article": "An article. Editorial content, not a field record.",
    "documentation": "Project or dataset documentation.",
    "dataset_metadata": (
        "Metadata describing a dataset. A statement about a data source, not "
        "about an organism at a place."
    ),
    "literature_title": (
        "A bibliographic title record. What it cites may include occurrences; "
        "the title row is not one."
    ),
    "literature_taxon": (
        "A taxon mentioned in literature. A mention is not a dated, placed "
        "record of presence."
    ),
    "migration": (
        "An ingest or schema migration artefact. Operational bookkeeping with "
        "no scientific content whatsoever."
    ),
    # Resolved from ambiguous on measured evidence: see the note below.
    "occurrence_stub": (
        "An ingest placeholder. Measured in production: 621,526 rows carrying "
        "zero coordinates, zero event dates and zero elevations -- so a stub "
        "asserts no place and cannot be evidence a taxon occurred at one. "
        "188,292 of them carry a GBIF key, and public.orchid_occurrence records "
        "188,285 rows sourced from 'records_source_record_id_backfill_safe', so "
        "the stubs have already been promoted into the canonical occurrence "
        "table. Counting them here would double-count rows that are measured "
        "there."
    ),
    "checklist": (
        "A checklist entry asserts a taxon belongs to a region's flora. That is "
        "a derived range statement, not a dated record of presence at a place."
    ),
}

# Types seen in production that this module deliberately refuses to decide.
# Each names what would settle it. Ambiguous never counts as an occurrence.
AMBIGUOUS_TYPES: dict[str, str] = {
    "community_observation": (
        "Named as an observation, which would qualify, but measured in "
        "production as 346 rows with zero coordinates and zero event dates. "
        "Whether these are locality-bearing field observations or community "
        "forum posts is not established by the type alone, and the data carries "
        "nothing to settle it. Withheld rather than guessed."
    ),
    "genomic_record": (
        "A sequence or genomic record. It qualifies only if it carries a "
        "voucher with a collection locality; 18 rows, none with coordinates or "
        "dates, so the voucher link is not established here."
    ),
    "record": (
        "Untyped catch-all. Carries no declared semantics to classify on, so it "
        "cannot be admitted without inspecting what produced it."
    ),
    "unknown": (
        "Explicitly recorded as unknown by the ingest. An explicit absence of "
        "type information is not a licence to assume occurrence."
    ),
    "(null)": (
        "No record_type recorded at all. Excluded for the same reason as "
        "'unknown': nothing establishes this as occurrence evidence."
    ),
}


def classify_record_type(record_type: str | None) -> tuple[str, str]:
    """Return ``(classification, reason)`` for one record_type value.

    Unknown values are AMBIGUOUS, never OCCURRENCE. A type this module has not
    seen cannot enter an occurrence count by default.
    """
    if record_type is None:
        return AMBIGUOUS, AMBIGUOUS_TYPES["(null)"]
    key = record_type.strip()
    if key in OCCURRENCE_TYPES:
        return OCCURRENCE, OCCURRENCE_TYPES[key]
    if key in NON_OCCURRENCE_TYPES:
        return NON_OCCURRENCE, NON_OCCURRENCE_TYPES[key]
    if key in AMBIGUOUS_TYPES:
        return AMBIGUOUS, AMBIGUOUS_TYPES[key]
    return AMBIGUOUS, (
        f"record_type {key!r} is not classified in occurrence_semantics. "
        "Unclassified types are excluded from occurrence measurement until "
        "their semantics are decided."
    )


def is_occurrence(record_type: str | None) -> bool:
    return classify_record_type(record_type)[0] == OCCURRENCE


def occurrence_type_values() -> tuple[str, ...]:
    """The admitted values, for building a SQL predicate."""
    return tuple(sorted(OCCURRENCE_TYPES))


def occurrence_predicate(alias: str = "o", column: str = "record_type") -> str:
    """A SQL predicate admitting only classified occurrence types.

    An allow-list, deliberately: a deny-list would admit every future ingest
    type the moment it appeared.
    """
    values = ", ".join("'" + v.replace("'", "''") + "'" for v in occurrence_type_values())
    return f"{alias}.{column} IN ({values})"


def classify_all(record_types: list[str | None]) -> dict[str, Any]:
    """Classify a full set of observed record_type values.

    Returned for evidence, so the classification applied to a measurement can be
    read back rather than inferred from the number it produced.
    """
    buckets: dict[str, list[dict[str, str]]] = {
        OCCURRENCE: [],
        NON_OCCURRENCE: [],
        AMBIGUOUS: [],
    }
    for rt in record_types:
        classification, reason = classify_record_type(rt)
        buckets[classification].append({"record_type": rt, "reason": reason})
    return {
        "contract": "OCU-OCCURRENCE-SEMANTICS-001",
        "definition": (
            "An occurrence is evidence that an orchid taxon occurred at a "
            "particular place: a legitimate observation, specimen, collection, "
            "or equivalent occurrence record."
        ),
        "rule": (
            "Classification is by declared semantics, never by the presence of "
            "coordinates, elevation, identifiers or taxon names. Unclassified "
            "types are ambiguous and are excluded from occurrence measurement."
        ),
        "buckets": buckets,
        "counts": {k: len(v) for k, v in buckets.items()},
    }
