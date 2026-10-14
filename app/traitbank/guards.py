"""Live-ingestion and privacy guards for TraitBank batches.

Every check returns violations rather than repairing the record; ingestion is
atomic, so one violation refuses the whole batch. Nothing is rewritten to make
a record pass.

Live mode refuses anything that is a test artefact rather than evidence:
records marked ``fixture_status``, placeholder hosts (``example.org`` and
friends), the reserved test DOI prefix ``10.5555``, synthetic markers, and
fixture-style ids. Canonical taxon and trait existence are checked against the
database by the ingestion service, not here.

Privacy: coordinates, e-mail addresses and phone numbers are refused in every
free-text field in every mode. Exact locality belongs to the occurrence store
and its locality policy, never to a trait record.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from .contract import oao_terms
from .models import (
    AssertionIn,
    EnvironmentRelationIn,
    ProvenanceIn,
    TraitBankBatch,
    TraitDefinitionIn,
)

PLACEHOLDER_RE = re.compile(
    r"(example\.(org|com|net)|oc-fixture|\bfixture\b|\[synthetic\]|synthetic contract fixture|"
    r"\bplaceholder\b|\blorem ipsum\b)",
    re.IGNORECASE,
)
FIXTURE_ID_RE = re.compile(
    r"^(fx[-:_]|fixture[-:_]|test[-:_]|placeholder[-:_])", re.IGNORECASE
)
TEST_DOI_RE = re.compile(r"10\.5555/", re.IGNORECASE)
# Decimal coordinate pairs, labelled lat/lon values, and degree-minute forms.
COORDINATE_RES = (
    re.compile(r"-?\d{1,2}\.\d{3,}\s*[,;/ ]\s*-?\d{1,3}\.\d{3,}"),
    re.compile(
        r"\b(lat(itude)?|lon(g|gitude)?)\s*[:=]?\s*-?\d{1,3}\.\d+", re.IGNORECASE
    ),
    re.compile(r"\d{1,3}\s*°\s*\d{1,2}\s*['′]"),
)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?<!\d)\+?\d[\d ()-]{8,}\d(?!\d)")


@dataclass(frozen=True)
class Violation:
    code: str
    where: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "where": self.where}


def _texts_of_provenance(p: ProvenanceIn) -> Iterable[tuple[str, str]]:
    for name in (
        "citation",
        "contributor",
        "locator",
        "original_text",
        "source_url",
        "source_id",
        "original_record_id",
    ):
        value = getattr(p, name)
        if value:
            yield name, value


def _privacy(where: str, field: str, text: str) -> list[Violation]:
    out = []
    if any(rx.search(text) for rx in COORDINATE_RES):
        out.append(Violation("COORDINATES_REFUSED", f"{where}.{field}"))
    if EMAIL_RE.search(text):
        out.append(Violation("PRIVATE_CONTACT_REFUSED", f"{where}.{field}"))
    # Citations legitimately carry page ranges and volume numbers; phone-like
    # digit runs are only checked in fields where a citation cannot appear.
    if field not in ("citation", "original_text", "source_url") and PHONE_RE.search(
        text
    ):
        out.append(Violation("PRIVATE_CONTACT_REFUSED", f"{where}.{field}"))
    return out


def _placeholder(where: str, field: str, text: str) -> list[Violation]:
    out = []
    if PLACEHOLDER_RE.search(text):
        out.append(Violation("PLACEHOLDER_REFUSED_IN_LIVE", f"{where}.{field}"))
    if TEST_DOI_RE.search(text):
        out.append(Violation("TEST_DOI_REFUSED_IN_LIVE", f"{where}.{field}"))
    return out


def _assertion_texts(a: AssertionIn) -> Iterable[tuple[str, str]]:
    yield from _texts_of_provenance(a.provenance)
    for name in ("notes", "scope_justification", "life_stage"):
        value = getattr(a, name)
        if value:
            yield name, value
    if a.value.verbatim:
        yield "value.verbatim", a.value.verbatim
    yield "subject.verbatim_taxon_name", a.subject.verbatim_taxon_name
    for i, habitat in enumerate(a.habitats):
        yield f"habitats[{i}]", habitat
    for i, link in enumerate(a.links):
        yield f"links[{i}].target_label", link.target_label
        yield f"links[{i}].target_id", link.target_id
        yield f"links[{i}].source_id", link.source_id
        if link.note:
            yield f"links[{i}].note", link.note


def _relation_texts(r: EnvironmentRelationIn) -> Iterable[tuple[str, str]]:
    yield from _texts_of_provenance(r.provenance)
    yield "statement", r.statement
    yield "environment_variable", r.environment_variable
    if r.test_design:
        yield "test_design", r.test_design


def _verified_requires_review(
    where: str, state: str, provenance: ProvenanceIn
) -> list[Violation]:
    # Mirrors oc-research-traits-v1: VERIFIED means a reviewer checked the
    # record against its source. A grower log or an unreviewed extraction
    # cannot assert it about itself.
    if state == "VERIFIED" and provenance.review_status not in (
        "accepted",
        "corrected",
    ):
        return [Violation("VERIFIED_REQUIRES_REVIEWED_PROVENANCE", where)]
    return []


def check_batch(batch: TraitBankBatch, *, live: bool) -> list[Violation]:
    violations: list[Violation] = []
    for a in batch.assertions:
        where = f"assertion:{a.assertion_id}"
        violations += _verified_requires_review(where, a.evidence_state, a.provenance)
        for field, text in _assertion_texts(a):
            violations += _privacy(where, field, text)
            if live:
                violations += _placeholder(where, field, text)
        if live:
            if a.provenance.fixture_status:
                violations.append(Violation("FIXTURE_RECORD_REFUSED_IN_LIVE", where))
            for field, value in (
                ("assertion_id", a.assertion_id),
                ("provenance.source_id", a.provenance.source_id),
                ("provenance.original_record_id", a.provenance.original_record_id),
            ):
                if FIXTURE_ID_RE.match(value):
                    violations.append(
                        Violation("FIXTURE_ID_REFUSED_IN_LIVE", f"{where}.{field}")
                    )
            for i, link in enumerate(a.links):
                if (
                    link.domain == "anatomical"
                    and link.target_id.startswith("OAO:")
                    and link.target_id not in oao_terms()
                ):
                    violations.append(
                        Violation("UNKNOWN_OAO_ID", f"{where}.links[{i}]")
                    )
    for r in batch.environment_relations:
        where = f"relation:{r.relation_id}"
        for field, text in _relation_texts(r):
            violations += _privacy(where, field, text)
            if live:
                violations += _placeholder(where, field, text)
        if live and r.provenance.fixture_status:
            violations.append(Violation("FIXTURE_RECORD_REFUSED_IN_LIVE", where))
    if live and FIXTURE_ID_RE.match(batch.batch_key):
        violations.append(Violation("FIXTURE_ID_REFUSED_IN_LIVE", "batch_key"))
    return violations


def check_definition(definition: TraitDefinitionIn, *, live: bool) -> list[Violation]:
    """OAO ids must exist in the vendored, pinned Brain registry."""
    terms = oao_terms()
    where = f"definition:{definition.trait_id}"
    violations: list[Violation] = []
    if definition.oao_character_id:
        term = terms.get(definition.oao_character_id)
        if term is None:
            violations.append(Violation("UNKNOWN_OAO_ID", f"{where}.oao_character_id"))
        elif term["term_type"] not in ("character", "measurement_character"):
            violations.append(
                Violation("OAO_ID_NOT_A_CHARACTER", f"{where}.oao_character_id")
            )
    for state in definition.states:
        if state.oao_id and state.oao_id not in terms:
            violations.append(
                Violation("UNKNOWN_OAO_ID", f"{where}.states[{state.state_id}]")
            )
    if live:
        for alias in definition.aliases:
            violations += _placeholder(where, "aliases", alias)
    return violations
