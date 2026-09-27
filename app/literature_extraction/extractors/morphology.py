"""Conservative source-reported morphology using the existing canonical taxonomy.

Only complete explicit lines are recognized. No inferred subject, fuzzy taxon,
location, measurement averaging, or scientific publication is performed.
"""

from __future__ import annotations

import re

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
    version = "1.0.0"
    pattern = re.compile(
        r"(?m)^(?P<name>[A-Z][a-z]+ [a-z][a-z-]+) "
        r"(?P<part>leaf|flower|petal|sepal|lip) "
        r"(?P<character>length|width) "
        r"(?P<value>\d+(?:\.\d+)?(?:[–-]\d+(?:\.\d+)?)?) "
        r"(?P<unit>mm|cm)\.[ \t]*$"
    )

    def __init__(self, taxonomy):
        self.taxonomy = taxonomy
        self.name_counts = {}
        for taxon in taxonomy.taxa.values():
            key = taxon.canonical_name.casefold()
            self.name_counts[key] = self.name_counts.get(key, 0) + 1

    async def run(self, context, paper):
        text = read_text_exact(context.source_path)
        paper.entities, paper.claims, paper.evidence = [], [], []
        for match in self.pattern.finditer(text):
            source_name = match["name"]
            taxon = self.taxonomy.resolve(source_name)
            # No unresolved or ambiguous name becomes a canonical claim.
            if (
                taxon is None
                or taxon.status != "accepted"
                or self.name_counts.get(source_name.casefold()) != 1
            ):
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
                    predicate=f"{match['part']}_{match['character']}",
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
        # Use only exact recognized spans as sections; never include locality in
        # a candidate excerpt. The complete acquired source remains restricted.
        paper.sections = [
            Section(section_id=f"section-{i}", text=e.excerpt, order=i, span=e.span)
            for i, e in enumerate(paper.evidence)
        ]
        return paper

    def output_count(self, paper):
        return len(paper.claims)
