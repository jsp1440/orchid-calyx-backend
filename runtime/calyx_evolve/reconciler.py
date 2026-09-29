"""EXPERIMENT stage: the bounded taxonomy reconciliation a candidate configures.

This is the only executable strategy in the loop.  Candidates do not supply
code; they supply a :class:`~runtime.calyx_evolve.candidates.ReconciliationConfig`
that this module interprets.  Everything here is pure and deterministic: given
the same fixture and the same configuration it produces byte-identical output.

Normalisation order is fixed and observable, so each knob is independently
meaningful:

1. ``collapse_whitespace`` — collapse internal runs of whitespace;
2. ``normalize_case`` — title-case the leading genus/epithet span;
3. ``strip_authorship`` — truncate to that span, discarding authorship.

The leading span is ``token[0]`` plus every following token that is
lower-case-initial and alphabetic (optionally hyphenated).  ``Lindl.``,
``&`` and ``Dodson`` all terminate the span, which is what separates a name
from its authorship without a bespoke author dictionary.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from runtime.calyx_evolve.candidates import ReconciliationConfig
from runtime.calyx_evolve.fixture import (
    EXPECT_ACCEPTED,
    EXPECT_UNRESOLVED,
    SYNONYM,
    ReferenceTaxon,
    TaxonomyFixture,
)
from runtime.calyx_evolve.provenance import content_hash
from runtime.calyx_evolve.sandbox import ExperimentSandbox

OUTCOME_ACCEPTED = EXPECT_ACCEPTED
OUTCOME_UNRESOLVED = EXPECT_UNRESOLVED

RULE_EXACT = "exact"
RULE_SYNONYM = "synonym_followed"
RULE_FUZZY = "fuzzy_unique"
RULE_ABSTAIN_AMBIGUOUS = "abstain_ambiguous"
RULE_ABSTAIN_NO_MATCH = "abstain_no_match"
RULE_ABSTAIN_EXACT_ONLY = "abstain_exact_only"

PROVENANCE_ORIGIN = "LOCKED_FIXTURE_RELEASE"

#: Provenance fields a resolution must carry to count as complete.
REQUIRED_RESOLUTION_PROVENANCE: tuple[str, ...] = (
    "origin",
    "release_id",
    "release_checksum",
    "matched_reference_id",
    "rule",
)

_TOKEN_RE = re.compile(r"\S+")
_EPITHET_RE = re.compile(r"^[a-z][a-z-]*$")
_WHITESPACE_RE = re.compile(r"\s+")


def name_span_end(text: str) -> int:
    """Return the end offset of the leading genus/epithet span in ``text``."""

    end = 0
    for index, match in enumerate(_TOKEN_RE.finditer(text)):
        if index == 0 or _EPITHET_RE.match(match.group(0)):
            end = match.end()
            continue
        break
    return end


def normalise_observed_name(name: str, config: ReconciliationConfig) -> str:
    """Apply the configured normalisation pipeline to an observed name."""

    text = _WHITESPACE_RE.sub(" ", name).strip() if config.collapse_whitespace else name.strip()
    if config.normalize_case:
        end = name_span_end(text)
        span = text[:end]
        if span:
            lowered = span.lower()
            text = lowered[:1].upper() + lowered[1:] + text[end:]
    if config.strip_authorship:
        text = text[: name_span_end(text)]
    return text


def edit_distance(left: str, right: str, *, ceiling: int) -> int:
    """Levenshtein distance, short-circuiting once it exceeds ``ceiling``."""

    if abs(len(left) - len(right)) > ceiling:
        return ceiling + 1
    previous = list(range(len(right) + 1))
    for i, left_char in enumerate(left, start=1):
        current = [i]
        row_min = i
        for j, right_char in enumerate(right, start=1):
            cost = 0 if left_char == right_char else 1
            value = min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost)
            current.append(value)
            row_min = min(row_min, value)
        if row_min > ceiling:
            return ceiling + 1
        previous = current
    return previous[-1]


@dataclass(frozen=True, slots=True)
class Resolution:
    record_id: str
    observed_name: str
    normalised_name: str
    outcome: str
    accepted_name: str | None
    matched_reference_id: str | None
    rule: str
    distance: int | None
    provenance: Mapping[str, Any]

    def provenance_complete(self) -> bool:
        if self.outcome != OUTCOME_ACCEPTED:
            # An abstention makes no taxonomic claim, so it carries no burden.
            return True
        return all(
            str(self.provenance.get(field, "")).strip()
            for field in REQUIRED_RESOLUTION_PROVENANCE
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "observed_name": self.observed_name,
            "normalised_name": self.normalised_name,
            "outcome": self.outcome,
            "accepted_name": self.accepted_name,
            "matched_reference_id": self.matched_reference_id,
            "rule": self.rule,
            "distance": self.distance,
            "provenance": dict(self.provenance),
        }


@dataclass(frozen=True, slots=True)
class ReconciliationArtifact:
    fixture_id: str
    fixture_hash: str
    release_id: str
    release_checksum: str
    config_hash: str
    resolutions: tuple[Resolution, ...]

    @property
    def artifact_digest(self) -> str:
        return content_hash(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixture_id": self.fixture_id,
            "fixture_hash": self.fixture_hash,
            "release_id": self.release_id,
            "release_checksum": self.release_checksum,
            "config_hash": self.config_hash,
            "resolutions": [resolution.to_dict() for resolution in self.resolutions],
        }


def _build_index(fixture: TaxonomyFixture) -> dict[str, ReferenceTaxon]:
    return {taxon.scientific_name: taxon for taxon in fixture.reference_taxa}


def _accepted_for(
    taxon: ReferenceTaxon, fixture: TaxonomyFixture, config: ReconciliationConfig
) -> tuple[str, str, str]:
    """Return ``(accepted_name, matched_reference_id, rule)`` for ``taxon``."""

    if taxon.status == SYNONYM and config.follow_synonyms and taxon.accepted_reference_id:
        accepted = fixture.by_reference_id(taxon.accepted_reference_id)
        if accepted is not None:
            return accepted.scientific_name, accepted.reference_id, RULE_SYNONYM
    return taxon.scientific_name, taxon.reference_id, RULE_EXACT


def _provenance(
    fixture: TaxonomyFixture,
    config: ReconciliationConfig,
    matched_reference_id: str,
    rule: str,
) -> dict[str, Any]:
    if not config.emit_provenance:
        return {}
    record: dict[str, Any] = {
        "origin": PROVENANCE_ORIGIN,
        "release_id": fixture.release_id,
        "release_checksum": fixture.release_checksum,
        "matched_reference_id": matched_reference_id,
        "rule": rule,
    }
    if config.emit_protected_locality:
        # A deliberately unsafe strategy: the output screen must catch this.
        record["exact_latitude"] = "-22.9068"
        record["exact_longitude"] = "-43.1729"
    return record


def run_reconciliation(
    config: ReconciliationConfig,
    fixture: TaxonomyFixture,
    sandbox: ExperimentSandbox,
) -> ReconciliationArtifact:
    """Execute ``config`` against ``fixture`` inside ``sandbox``."""

    if not sandbox.started:
        sandbox.start()

    index = _build_index(fixture)
    accepted_names = sorted(taxon.scientific_name for taxon in fixture.reference_taxa)
    resolutions: list[Resolution] = []

    for record in fixture.records:
        sandbox.checkpoint()
        normalised = normalise_observed_name(record.observed_name, config)

        taxon = index.get(normalised)
        if taxon is not None:
            accepted_name, reference_id, rule = _accepted_for(taxon, fixture, config)
            resolutions.append(
                Resolution(
                    record_id=record.record_id,
                    observed_name=record.observed_name,
                    normalised_name=normalised,
                    outcome=OUTCOME_ACCEPTED,
                    accepted_name=accepted_name,
                    matched_reference_id=reference_id,
                    rule=rule,
                    distance=0,
                    provenance=_provenance(fixture, config, reference_id, rule),
                )
            )
            continue

        if config.fuzzy_max_distance <= 0:
            resolutions.append(
                Resolution(
                    record_id=record.record_id,
                    observed_name=record.observed_name,
                    normalised_name=normalised,
                    outcome=OUTCOME_UNRESOLVED,
                    accepted_name=None,
                    matched_reference_id=None,
                    rule=RULE_ABSTAIN_EXACT_ONLY,
                    distance=None,
                    provenance={},
                )
            )
            continue

        ceiling = config.fuzzy_max_distance
        scored = [
            (edit_distance(normalised, candidate_name, ceiling=ceiling), candidate_name)
            for candidate_name in accepted_names
        ]
        within = sorted((d, n) for d, n in scored if d <= ceiling)
        if not within:
            resolutions.append(
                Resolution(
                    record_id=record.record_id,
                    observed_name=record.observed_name,
                    normalised_name=normalised,
                    outcome=OUTCOME_UNRESOLVED,
                    accepted_name=None,
                    matched_reference_id=None,
                    rule=RULE_ABSTAIN_NO_MATCH,
                    distance=None,
                    provenance={},
                )
            )
            continue

        best_distance = within[0][0]
        tied = [name for distance, name in within if distance == best_distance]
        if len(tied) > 1 and config.ambiguity_guard:
            resolutions.append(
                Resolution(
                    record_id=record.record_id,
                    observed_name=record.observed_name,
                    normalised_name=normalised,
                    outcome=OUTCOME_UNRESOLVED,
                    accepted_name=None,
                    matched_reference_id=None,
                    rule=RULE_ABSTAIN_AMBIGUOUS,
                    distance=best_distance,
                    provenance={},
                )
            )
            continue

        matched = index[tied[0]]
        accepted_name, reference_id, _ = _accepted_for(matched, fixture, config)
        resolutions.append(
            Resolution(
                record_id=record.record_id,
                observed_name=record.observed_name,
                normalised_name=normalised,
                outcome=OUTCOME_ACCEPTED,
                accepted_name=accepted_name,
                matched_reference_id=reference_id,
                rule=RULE_FUZZY,
                distance=best_distance,
                provenance=_provenance(fixture, config, reference_id, RULE_FUZZY),
            )
        )

    return ReconciliationArtifact(
        fixture_id=fixture.fixture_id,
        fixture_hash=fixture.fixture_hash,
        release_id=fixture.release_id,
        release_checksum=fixture.release_checksum,
        config_hash=config.config_hash,
        resolutions=tuple(resolutions),
    )
