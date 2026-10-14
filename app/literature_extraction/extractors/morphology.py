"""Conservative source-reported morphology using the existing canonical taxonomy.

Only complete explicit lines are recognized. No inferred subject, fuzzy taxon,
location, measurement averaging, or scientific publication is performed.
"""

from __future__ import annotations

import re
from typing import ClassVar

from ..ingest import read_text_exact
from ..models import (
    Claim,
    Entity,
    Evidence,
    Identifier,
    Provenance,
    Section,
    SourceSpan,
)
from .base import Extractor


class CanonicalMorphologyExtractor(Extractor):
    name = "canonical_morphology"
    version = "1.1.0"
    pattern = re.compile(
        r"(?m)^(?P<name>[A-Z][a-z]+ [a-z][a-z-]+) "
        r"(?P<part>leaf|flower|petal|sepal|lip|column|staminode|inflorescence) "
        r"(?P<character>length|width) "
        r"(?P<value>\d+(?:\.\d+)?(?:[–-]\d+(?:\.\d+)?)?) "
        r"(?P<unit>mm|cm)\.[ \t]*$"
    )

    # Labels establish the evidence kind, never a normalized botanical state.
    labels: ClassVar[dict[str, str]] = {
        "character": "character_description", "description": "taxon_description",
        "diagnosis": "diagnosis", "leaf": "leaf_description",
        "flower": "flower_description", "sepal": "sepal_description",
        "petal": "petal_description", "lip": "lip_description",
        "column": "column_description", "staminode": "staminode_description",
        "inflorescence": "inflorescence_description", "habit": "growth_habit",
        "habitat": "habitat", "elevation": "elevation",
        "phenology": "phenology", "substrate": "substrate",
        "diagnostic comparison": "diagnostic_comparison", "key couplet": "key_couplet",
        "variation": "variation",
    }
    labeled_pattern = re.compile(
        r"(?m)^(?P<name>[A-Z][a-z]+ [a-z][a-z-]+) "
        r"(?P<label>" + "|".join(labels) + r"): (?P<value>[^\n]+)$"
    )
    # Closed vocabulary intentionally rejects place names and unsupported prose.
    # Unknown terms remain only in the restricted source, with a count-only
    # manifest warning for expert review. Coordinates/URLs/identifiers fail too.
    vocabulary = frozenset("""
        a an the and or with without to of in on at is are than from by
        leaf leaves flower flowers petal petals sepal sepals lip lips column
        staminode inflorescence inflorescences stem stems root roots bract bracts
        dorsal lateral median basal apical upper lower margin margins surface
        length width long wide broad narrow short longer shorter broader narrower
        ovate obovate elliptic elliptical lanceolate linear oblong rounded acute
        obtuse acuminate bifid entire dentate serrate ciliate glabrous pubescent hairy
        green yellow white pink red purple brown mottled spotted striped pale dark
        erect arching spreading pendent curved twisted flat folded inflated
        solitary paired several many few single two three four five
        terrestrial epiphytic lithophytic herb perennial evergreen deciduous
        forest forests woodland grassland shaded open moist wet dry humid
        limestone granite rock rocks rocky soil humus litter moss mossy bark
        lowland montane subalpine tropical subtropical temperate
        flowering fruiting january february march april may june july august
        september october november december spring summer autumn winter year round
        variable varies variation usually sometimes rarely occasionally approximately
        about up mm cm m compared unlike similar differs distinct contrasting
        absent present smooth keeled veined reticulate densely sparsely
    """.split())  # noqa: SIM905 - grouped botanical vocabulary

    def _matches(self, text, paper):
        matches = [(match, f"{match['part']}_{match['character']}")
                   for match in self.pattern.finditer(text)]
        unsupported = 0
        for match in self.labeled_pattern.finditer(text):
            value = match["value"].strip()
            # Complete exact span retained only after every token is admitted.
            safe = re.fullmatch(r"[A-Za-z0-9 ,.;:()–−-]+", value) is not None
            words = re.findall(r"[A-Za-z]+", value)
            safe = safe and bool(words) and all(word.lower() in self.vocabulary for word in words)
            safe = safe and not re.search(r"\d+\.\d+\s*,\s*\d+\.\d+", value)
            if match["label"] in {"habitat", "habit", "substrate", "phenology"}:
                safe = safe and not re.search(r"\d", value)
            # Reject internal capitals: even vocabulary words may form named
            # localities (for example Green Forest). Sentence-initial case is fine.
            safe = safe and all(word.islower() for word in words[1:])
            if safe:
                matches.append((match, self.labels[match["label"]]))
            else:
                unsupported += 1
        if unsupported:
            paper.analysis_manifest.warnings.append(
                f"canonical_morphology: {unsupported} unsupported labeled spans withheld; expert extraction review required"
            )
        return sorted(matches, key=lambda item: item[0].start())

    def __init__(self, taxonomy):
        self.taxonomy = taxonomy
        self.name_counts = {}
        for taxon in taxonomy.taxa.values():
            key = taxon.canonical_name.casefold()
            self.name_counts[key] = self.name_counts.get(key, 0) + 1

    async def run(self, context, paper):
        text = read_text_exact(context.source_path)
        paper.entities, paper.claims, paper.evidence = [], [], []
        unbound = 0
        for match, predicate in self._matches(text, paper):
            source_name = match["name"]
            taxon = self.taxonomy.resolve(source_name)
            # No unresolved or ambiguous name becomes a canonical claim.
            if (
                taxon is None
                or taxon.status != "accepted"
                or self.name_counts.get(source_name.casefold()) != 1
            ):
                unbound += 1
                continue
            index = len(paper.claims) + 1
            eid, cid, ev_id = f"entity-{index}", f"claim-{index}", f"evidence-{index}"
            excerpt = match.group().rstrip()
            span = SourceSpan(
                char_start=match.start(), char_end=match.start() + len(excerpt)
            )
            provenance = Provenance(
                method="source_reported",
                confidence=1,
                extractor=self.name,
                extractor_version=self.version,
            )
            paper.entities.append(
                Entity(
                    entity_id=eid,
                    entity_type="taxon",
                    name=source_name,
                    normalized_name=source_name.casefold(),
                    mentions=[span],
                    external_ids=[
                        Identifier(
                            scheme="local",
                            value=f"{taxon.provenance.get('identity_namespace', 'world_plants')}:{taxon.canonical_id}",
                        )
                    ],
                    provenance=provenance,
                )
            )
            paper.claims.append(
                Claim(
                    claim_id=cid,
                    statement=excerpt,
                    claim_type="result",
                    subject_ids=[eid],
                    predicate=predicate,
                    evidence_ids=[ev_id],
                    provenance=provenance,
                )
            )
            paper.evidence.append(
                Evidence(
                    evidence_id=ev_id,
                    excerpt=excerpt,
                    span=span,
                    evidence_type="text",
                    supports_ids=[cid],
                )
            )
        if unbound:
            paper.analysis_manifest.warnings.append(
                f"canonical_morphology: {unbound} unresolved or ambiguous taxon spans withheld; taxonomy review required"
            )
        # Use only exact recognized spans as sections; never include locality in
        # a candidate excerpt. The complete acquired source remains restricted.
        paper.sections = [
            Section(section_id=f"section-{i}", text=e.excerpt, order=i, span=e.span)
            for i, e in enumerate(paper.evidence)
        ]
        return paper

    def output_count(self, paper):
        return len(paper.claims)


MORPHOLOGY_PREDICATES = frozenset(CanonicalMorphologyExtractor.labels.values()) | {
    f"{part}_{dimension}"
    for part in ("leaf", "flower", "petal", "sepal", "lip", "column", "staminode", "inflorescence")
    for dimension in ("length", "width")
}
