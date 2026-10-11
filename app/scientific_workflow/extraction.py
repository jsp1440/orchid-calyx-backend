"""Deterministic morphological character extraction.

Rule-based extraction from botanical description prose into typed
:class:`~app.scientific_workflow.models.CharacterObservationRecord` values.

Design rules (mirroring the mission constraints):

* The extractor is deterministic and offline — no model calls, no paid
  providers.  Every rule is inspectable below.
* A statement is never "verified" just because it was extracted: every record
  is born ``unreviewed`` with ``rule_extracted`` provenance and a confidence
  ceiling below 1.0.
* ABSENT requires an explicit negation in the text ("spur absent",
  "pseudobulbs absent").  Silence produces UNKNOWN — missing data is not
  biological absence.
* INAPPLICABLE is derived by applicability rules (e.g. spur length when the
  spur is explicitly absent), never from silence.
* Measurements keep the original unit verbatim and add a millimetre-normalised
  value.

The module also provides :class:`MorphologyExtractor`, a drop-in
``app.literature_extraction.extractors.base.Extractor`` so the same rules run
inside the existing literature pipeline and land in ``PaperKnowledge`` as
measurements, claims and evidence with proper spans.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Literal

from .models import (
    CharacterObservationRecord,
    EvidenceKind,
    ProvenanceMethod,
    SourceCitation,
    StateKind,
    TextSpan,
    stable_id,
)

EXTRACTOR_NAME = "scientific-workflow-morphology"
EXTRACTOR_VERSION = "0.1.0"
RULE_CONFIDENCE = 0.8  # rule-extracted ceiling; human review still required

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_NUMBER_RE = r"(\d+(?:\.\d+)?)"


@dataclass(frozen=True)
class StateRule:
    """One ordered rule: regex -> state/value for a character."""

    pattern: str
    state_kind: Literal["present", "absent"]
    value: Any = None  # static value, or a group name for dynamic extraction
    unit_group: str | None = None

    def compiled(self) -> re.Pattern[str]:
        return re.compile(self.pattern, re.IGNORECASE)


@dataclass(frozen=True)
class CharacterDefinition:
    character_id: str
    label: str
    value_type: Literal["categorical", "numeric", "numeric_range", "multi_state"]
    lexicon_term_id: str | None
    oao_entity_key: str | None
    oao_quality_key: str | None
    weight: float
    description: str
    rules: tuple[StateRule, ...] = field(default_factory=tuple)
    # Applicability: (governing_character, required_state) — when the governing
    # character is ABSENT, this character is INAPPLICABLE.
    applicable_unless_absent: str | None = None
    # States that are categorical assertions of biological absence map value None.
    unit: str | None = None  # expected normalised unit for numeric characters


CHARACTERS: tuple[CharacterDefinition, ...] = (
    CharacterDefinition(
        character_id="habit",
        label="Growth habit",
        value_type="categorical",
        lexicon_term_id=None,
        oao_entity_key=None,
        oao_quality_key=None,
        weight=2.0,
        description="Life form / substrate of the plant as stated by the source.",
        rules=(
            StateRule(r"\bsubterranean\b", "present", "subterranean"),
            StateRule(r"\bterrestrial\b", "present", "terrestrial"),
            StateRule(r"\bepiphyt(?:ic|es?)\b", "present", "epiphytic"),
            StateRule(r"\blithophyt(?:ic|es?)\b", "present", "lithophytic"),
        ),
    ),
    CharacterDefinition(
        character_id="growth_form",
        label="Growth form",
        value_type="categorical",
        lexicon_term_id=None,
        oao_entity_key=None,
        oao_quality_key=None,
        weight=2.0,
        description="Monopodial vs sympodial construction, only when stated explicitly.",
        rules=(
            StateRule(r"\bmonopodial\b", "present", "monopodial"),
            StateRule(r"\bsympodial\b", "present", "sympodial"),
        ),
    ),
    CharacterDefinition(
        character_id="pseudobulb_presence",
        label="Pseudobulb presence",
        value_type="categorical",
        lexicon_term_id="pseudobulb",
        oao_entity_key="pseudobulb",
        oao_quality_key="presence",
        weight=3.0,
        description="Whether pseudobulbs are present; absence requires an explicit statement.",
        rules=(
            StateRule(r"pseudobulbs?\s+absent", "absent", "absent"),
            StateRule(r"pseudobulbs?\s+\d", "present", "present"),
            StateRule(r"\bwith\s+(?:[a-z-]+\s+){0,3}pseudobulbs?\b", "present", "present"),
        ),
    ),
    CharacterDefinition(
        character_id="leaf_presence",
        label="Leaf presence",
        value_type="categorical",
        lexicon_term_id="leaf",
        oao_entity_key=None,
        oao_quality_key="presence",
        weight=2.0,
        description="Whether photosynthetic leaves are present; absence requires an explicit statement.",
        rules=(
            StateRule(r"(?:true\s+)?leaves\s+absent", "absent", "absent"),
            StateRule(r"\bleafless\b", "absent", "absent"),
            StateRule(r"\bleaves\s+\d", "present", "present"),
            StateRule(r"\bleaf\s+solitary", "present", "present"),
            StateRule(r"\bleaves\s+distichous", "present", "present"),
            StateRule(r"\bleafy\s+stem", "present", "present"),
        ),
    ),
    CharacterDefinition(
        character_id="leaf_shape",
        label="Leaf shape",
        value_type="categorical",
        lexicon_term_id="leaf",
        oao_entity_key=None,
        oao_quality_key="shape",
        weight=1.0,
        description="Lamina shape as stated; inapplicable when leaves are explicitly absent.",
        applicable_unless_absent="leaf_presence",
        rules=(
            StateRule(r"\bstrap-shaped\b|\blorate\b", "present", "strap-shaped"),
            StateRule(r"\belliptic\b", "present", "elliptic"),
            StateRule(r"\boblong\b", "present", "oblong"),
            StateRule(r"\bovate-lanceolate\b", "present", "ovate-lanceolate"),
            StateRule(r"\blanceolate\b", "present", "lanceolate"),
            StateRule(r"\bobovate\b", "present", "obovate"),
            StateRule(r"\blinear\b", "present", "linear"),
        ),
    ),
    CharacterDefinition(
        character_id="labellum_form",
        label="Labellum form",
        value_type="categorical",
        lexicon_term_id="labellum",
        oao_entity_key="labellum",
        oao_quality_key="shape",
        weight=4.0,
        description="Gross form of the labellum (pouch, lobing, reduction).",
        rules=(
            StateRule(r"labellum[^.]{0,120}?\breduced\b", "present", "reduced"),
            StateRule(r"labellum[^.]{0,120}?(?:pouch|saccate|slipper)", "present", "saccate-pouch"),
            StateRule(r"labellum[^.]{0,120}?(?:deeply\s+)?3-lobed", "present", "3-lobed"),
            StateRule(r"labellum[^.]{0,120}?\bunlobed\b", "present", "unlobed"),
        ),
    ),
    CharacterDefinition(
        character_id="spur_presence",
        label="Floral spur presence",
        value_type="categorical",
        lexicon_term_id="floral_spur",
        oao_entity_key="floral spur / nectary",
        oao_quality_key="presence",
        weight=2.0,
        description="Whether a floral spur is present; absence requires an explicit statement.",
        rules=(
            StateRule(r"(?:floral\s+)?spur\s+absent", "absent", "absent"),
            StateRule(r"\bspurred\b", "present", "present"),
            StateRule(r"\bspur\s+(?:conical|cylindrical|slender|short)\b", "present", "present"),
        ),
    ),
    CharacterDefinition(
        character_id="spur_length_mm",
        label="Spur length (mm)",
        value_type="numeric_range",
        lexicon_term_id="floral_spur",
        oao_entity_key="floral spur / nectary",
        oao_quality_key="length",
        weight=2.0,
        description="Spur length range; inapplicable when the spur is explicitly absent.",
        applicable_unless_absent="spur_presence",
        unit="mm",
        rules=(
            StateRule(
                rf"\bspur\b[^.]{{0,40}}?{_NUMBER_RE}\s*[-–]\s*{_NUMBER_RE}\s*(mm|cm)\b",
                "present",
                "__range__",
                unit_group="unit",
            ),
        ),
    ),
    CharacterDefinition(
        character_id="pollinia_count",
        label="Pollinia number",
        value_type="numeric",
        lexicon_term_id="pollinium",
        oao_entity_key="pollinium",
        oao_quality_key="count",
        weight=3.0,
        description="Number of pollinia as stated by the source.",
        rules=(
            StateRule(rf"\bpollinia\s+{_NUMBER_RE}\b", "present", "__number__"),
        ),
    ),
    CharacterDefinition(
        character_id="resupination",
        label="Resupination",
        value_type="categorical",
        lexicon_term_id="resupination",
        oao_entity_key=None,
        oao_quality_key=None,
        weight=2.0,
        description="Whether flowers are resupinate; negation is matched before the bare term.",
        rules=(
            StateRule(r"\bnot\s+resupinate\b|\bnon-resupinate\b", "absent", "absent"),
            StateRule(r"\bresupinate\b", "present", "present"),
        ),
    ),
    CharacterDefinition(
        character_id="fragrance",
        label="Floral fragrance",
        value_type="categorical",
        lexicon_term_id=None,
        oao_entity_key=None,
        oao_quality_key=None,
        weight=1.0,
        description="Fragrance only when stated; silence stays UNKNOWN (never treated as absent).",
        rules=(
            StateRule(r"\bfragrant\b", "present", "present"),
            StateRule(r"\bscentless\b|\bwithout\s+scent\b|\bnot\s+fragrant\b", "absent", "absent"),
        ),
    ),
    CharacterDefinition(
        character_id="flowering_period",
        label="Flowering period",
        value_type="categorical",
        lexicon_term_id=None,
        oao_entity_key=None,
        oao_quality_key=None,
        weight=1.0,
        description="Phenology statement as written by the source.",
        rules=(
            StateRule(r"\bflowering\s+([a-z]+\s+(?:to|through|-)\s+[a-z]+|in\s+[a-z]+)\b", "present", "__group1__"),
        ),
    ),
)


def character_definition(character_id: str) -> CharacterDefinition:
    for definition in CHARACTERS:
        if definition.character_id == character_id:
            return definition
    raise KeyError(f"unknown character: {character_id}")


def _to_mm(value: float, unit: str) -> float:
    return value * 10.0 if unit.casefold() == "cm" else value


@dataclass(frozen=True)
class ParsedDescription:
    """A fixture/source document split into citation metadata and body text.

    ``body`` is an *unmodified* slice of the original text starting at
    ``body_offset`` so that character spans can be re-projected onto the raw
    source (the literature pipeline validates evidence spans byte-for-byte).
    """

    citation: SourceCitation
    taxon_name: str
    body: str
    body_offset: int = 0


def parse_description_text(text: str, *, fallback_source_id: str) -> ParsedDescription:
    """Parse the ``---`` front matter used by authorised fixture files.

    Files without front matter are treated as unreviewed sources with unknown
    rights — never as cleared content.
    """

    header: dict[str, str] = {}
    body = text
    body_offset = 0
    match = re.match(r"\A---\s*\n(.*?)\n---\s*\n", text, flags=re.DOTALL)
    if match:
        for line in match.group(1).splitlines():
            if ":" in line:
                key, _, value = line.partition(":")
                header[key.strip()] = value.strip()
        body_offset = match.end()
        body = text[body_offset:]
    citation = SourceCitation(
        source_id=header.get("fixture_id") or header.get("source_id") or fallback_source_id,
        source_name=header.get("attribution") or "Unattributed source",
        source_type=header.get("source_type") or "unknown",
        rights_status=header.get("rights_status") or "unknown_requires_review",
        attribution=header.get("attribution") or "unspecified",
        license=header.get("license"),
        notes=header.get("notes"),
    )
    return ParsedDescription(
        citation=citation,
        taxon_name=header.get("taxon_name") or "",
        body=body,
        body_offset=body_offset,
    )


def _sentences(body: str) -> Iterable[tuple[int, str]]:
    offset = 0
    for sentence in _SENTENCE_RE.split(body):
        index = body.find(sentence, offset)
        if index == -1:
            index = offset
        yield index, sentence
        offset = index + len(sentence)


def extract_characters(
    parsed: ParsedDescription,
    taxon_id: str,
    *,
    evidence_kind: EvidenceKind = EvidenceKind.LITERATURE,
    provenance_method: ProvenanceMethod = ProvenanceMethod.RULE_EXTRACTED,
    confidence: float = RULE_CONFIDENCE,
) -> list[CharacterObservationRecord]:
    """Run every character rule-set over one description body.

    Returns one record per character definition — reported characters with
    their value and source span, unreported characters as UNKNOWN with no
    span.  Applicability (INAPPLICABLE) is resolved in a second pass once the
    governing character states are known.
    """

    records: list[CharacterObservationRecord] = []
    for definition in CHARACTERS:
        found: CharacterObservationRecord | None = None
        for sentence_start, sentence in _sentences(parsed.body):
            if found is not None:
                break
            for rule in definition.rules:
                match = rule.compiled().search(sentence)
                if match is None:
                    continue
                start = sentence_start + match.start()
                end = sentence_start + match.end()
                span = TextSpan(start=start, end=end, excerpt=parsed.body[start:end])
                state_kind = StateKind.PRESENT if rule.state_kind == "present" else StateKind.ABSENT
                value: Any = rule.value
                unit_original: str | None = None
                unit_normalized: str | None = None
                value_normalized: Any = None
                if rule.value == "__number__":
                    value = float(match.group(1))
                    if value.is_integer():
                        value = int(value)
                elif rule.value == "__range__":
                    unit_original = match.group(3)
                    low = _to_mm(float(match.group(1)), unit_original)
                    high = _to_mm(float(match.group(2)), unit_original)
                    value = {"min": float(match.group(1)), "max": float(match.group(2))}
                    unit_normalized = "mm"
                    value_normalized = {"min": low, "max": high}
                elif rule.value == "__group1__":
                    value = match.group(1).strip()
                elif state_kind == StateKind.ABSENT:
                    value = "absent"
                found = CharacterObservationRecord(
                    record_id=stable_id(
                        parsed.citation.source_id, taxon_id, definition.character_id, prefix="obs"
                    ),
                    taxon_id=taxon_id,
                    character_id=definition.character_id,
                    state_kind=state_kind,
                    value=value,
                    span=span,
                    source=parsed.citation,
                    provenance_method=provenance_method,
                    evidence_kind=evidence_kind,
                    confidence=confidence,
                    extractor=EXTRACTOR_NAME,
                    extractor_version=EXTRACTOR_VERSION,
                    unit_original=unit_original,
                    unit_normalized=unit_normalized,
                    value_normalized=value_normalized,
                )
                break
        if found is None:
            found = CharacterObservationRecord(
                record_id=stable_id(
                    parsed.citation.source_id, taxon_id, definition.character_id, "unknown", prefix="obs"
                ),
                taxon_id=taxon_id,
                character_id=definition.character_id,
                state_kind=StateKind.UNKNOWN,
                value=None,
                span=None,
                source=parsed.citation,
                provenance_method=provenance_method,
                evidence_kind=evidence_kind,
                confidence=0.0,
                extractor=EXTRACTOR_NAME,
                extractor_version=EXTRACTOR_VERSION,
            )
        records.append(found)

    # Second pass: applicability.  A character whose governor is explicitly
    # ABSENT is INAPPLICABLE — e.g. spur length on a spurless flower.
    by_character = {record.character_id: record for record in records}
    resolved: list[CharacterObservationRecord] = []
    for record in records:
        definition = character_definition(record.character_id)
        governor_id = definition.applicable_unless_absent
        governor = by_character.get(governor_id) if governor_id else None
        if (
            record.state_kind == StateKind.UNKNOWN
            and governor is not None
            and governor.state_kind == StateKind.ABSENT
        ):
            record = replace(record, state_kind=StateKind.INAPPLICABLE)
        resolved.append(record)
    return resolved
