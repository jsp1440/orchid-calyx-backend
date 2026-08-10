from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from typing import Any

from app.literature_extraction.models import GlossaryTerm


@dataclass(frozen=True, slots=True)
class WordElement:
    element_id: str
    form: str
    language: str
    kind: str
    meaning: str
    variants: tuple[str, ...] = ()
    botanical_examples: tuple[str, ...] = ()
    note: str | None = None


WORD_ELEMENTS: tuple[WordElement, ...] = (
    WordElement("root:anth", "anth-/antho-", "Greek", "combining_form", "flower", ("anth", "antho"), ("anthesis", "Anthurium")),
    WordElement("root:dendr", "dendr-/dendro-", "Greek", "combining_form", "tree", ("dendr", "dendro"), ("Dendrobium",)),
    WordElement("root:ep", "epi-", "Greek", "prefix", "upon, on, over", ("epi",), ("epiphyte", "Epidendrum")),
    WordElement("root:gyn", "gyn-/gyno-", "Greek", "combining_form", "female; ovary or pistil in botanical compounds", ("gyn", "gyno"), ("gynostemium",)),
    WordElement("root:hydr", "hydr-/hydro-", "Greek", "combining_form", "water", ("hydr", "hydro"), ("hydrophyte",)),
    WordElement("root:labi", "labi-/labell-", "Latin", "root", "lip; little lip", ("labi", "labell"), ("labellum",)),
    WordElement("root:lith", "lith-/litho-", "Greek", "combining_form", "stone", ("lith", "litho"), ("lithophyte",)),
    WordElement("root:macr", "macr-/macro-", "Greek", "combining_form", "large, long", ("macr", "macro"), ("macranthum",)),
    WordElement("root:micr", "micr-/micro-", "Greek", "combining_form", "small", ("micr", "micro"), ("microphyllum",)),
    WordElement("root:mon", "mon-/mono-", "Greek", "combining_form", "one, single", ("mon", "mono"), ("monopodial",)),
    WordElement("root:myc", "myc-/myco-", "Greek", "combining_form", "fungus", ("myc", "myco"), ("mycorrhiza",)),
    WordElement("root:necr", "necr-/necro-", "Greek", "combining_form", "dead", ("necr", "necro"), ("necrosis",)),
    WordElement("root:phyll", "phyll-/phyllo-", "Greek", "combining_form", "leaf", ("phyll", "phyllo"), ("microphyllum",)),
    WordElement("root:phyt", "phyt-/phyto-", "Greek", "combining_form", "plant", ("phyt", "phyto"), ("epiphyte", "phytogeography")),
    WordElement("root:pollin", "pollin-", "Latin", "root", "pollen", ("pollin",), ("pollinium", "pollination")),
    WordElement("root:pseud", "pseud-/pseudo-", "Greek", "combining_form", "false, resembling but not truly", ("pseud", "pseudo"), ("pseudobulb",)),
    WordElement("root:rhiz", "rhiz-/rhizo-", "Greek", "combining_form", "root", ("rhiz", "rhizo"), ("rhizome", "mycorrhiza")),
    WordElement("root:stemon", "stemon-/stamin-", "Greek/Latin", "root", "stamen", ("stemon", "stamin"), ("gynostemium", "staminal")),
    WordElement("root:xer", "xer-/xero-", "Greek", "combining_form", "dry", ("xer", "xero"), ("xerophyte",)),
    WordElement("root:alb", "alb-/albus/alba/album", "Latin", "root", "white", ("alb", "albus", "alba", "album"), ("forma alba",)),
    WordElement("root:aur", "aur-/aureus/aurea/aureum", "Latin", "root", "golden", ("aur", "aureus", "aurea", "aureum"), ("aureum",)),
    WordElement("root:grand", "grand-/grandis", "Latin", "root", "large, great", ("grand", "grandis"), ("grandiflora",)),
    WordElement("root:flor", "flor-/flori-", "Latin", "combining_form", "flower", ("flor", "flori"), ("grandiflora",)),
    WordElement("root:long", "long-/longus", "Latin", "root", "long", ("long", "longus", "longa", "longum"), ("longifolium",)),
    WordElement("root:foli", "foli-", "Latin", "combining_form", "leaf", ("foli",), ("longifolium",)),
)


BOTANICAL_LATIN_BACKGROUND: dict[str, Any] = {
    "title": "Botanical Latin: a practical background",
    "summary": (
        "Botanical Latin is the international, Latinized language traditionally used to form "
        "scientific plant names and much descriptive terminology. It draws heavily from Classical "
        "and later Latin while also Latinizing Greek and names from many other languages."
    ),
    "principles": [
        "A species name combines a genus name with a specific epithet; the epithet alone is not the species name.",
        "A specific epithet may be an adjective, a noun in the genitive, or a noun in apposition.",
        "Adjectival epithets normally agree grammatically with the gender of the genus, which is why endings may vary among -us, -a, and -um or other declensional patterns.",
        "Many botanical compounds use Greek roots and combining forms transmitted through Latinized scientific vocabulary.",
        "Nomenclatural correctness and biological identification are different questions: a correctly formed name does not itself prove the identity of a plant.",
        "Pronunciation traditions vary internationally; spelling, authorship, typification, and nomenclatural status are the governance-critical properties.",
    ],
    "common_patterns": [
        {"pattern": "-ensis / -ense", "meaning": "from, or associated with, a place"},
        {"pattern": "-anus / -ana / -anum", "meaning": "belonging to or associated with"},
        {"pattern": "-oides", "meaning": "resembling"},
        {"pattern": "-phyllus / -phylla / -phyllum", "meaning": "having leaves of the stated kind"},
        {"pattern": "-florus / -flora / -florum", "meaning": "having flowers of the stated kind or number"},
    ],
    "governance_note": (
        "This background is explanatory reference material. Etymological decomposition is a lexical aid, "
        "not proof of a taxon's diagnostic character, nomenclatural history, or original author's intent."
    ),
}


def _normalize(value: str) -> str:
    return " ".join(value.casefold().strip().split())


def _tokenize(value: str) -> list[str]:
    return re.findall(r"[a-z]+", _normalize(value))


class BotanicalLanguageService:
    """Connect extracted glossary candidates with canonical concepts and lexical aids."""

    def __init__(self, concept_search: Callable[[str], dict[str, Any]] | None = None) -> None:
        self.concept_search = concept_search

    def roots_for(self, term: str) -> list[dict[str, Any]]:
        tokens = _tokenize(term)
        matches: list[tuple[int, WordElement, str]] = []
        for token in tokens:
            for element in WORD_ELEMENTS:
                for variant in sorted(element.variants, key=len, reverse=True):
                    if len(variant) < 3:
                        continue
                    position = token.find(variant)
                    if position >= 0:
                        matches.append((position, element, variant))
                        break
        seen: set[str] = set()
        result: list[dict[str, Any]] = []
        for position, element, matched in sorted(
            matches,
            key=lambda item: (item[0], -len(item[2]), item[1].element_id),
        ):
            if element.element_id in seen:
                continue
            seen.add(element.element_id)
            result.append(
                {
                    **asdict(element),
                    "matched_form": matched,
                    "analysis_state": "MORPHOLOGICAL_HINT",
                }
            )
        return result

    def analyze_term(
        self,
        term: str,
        *,
        glossary_term: GlossaryTerm | None = None,
    ) -> dict[str, Any]:
        normalized = _normalize(term)
        concept_matches: dict[str, Any] | None = None
        if self.concept_search is not None:
            concept_matches = self.concept_search(term)
        return {
            "term": term,
            "normalized_term": normalized,
            "glossary": (
                {
                    "term_id": glossary_term.term_id,
                    "status": glossary_term.status,
                    "glossary_entry_id": glossary_term.glossary_entry_id,
                    "senses": list(glossary_term.senses),
                    "provenance": glossary_term.provenance.model_dump(mode="json"),
                }
                if glossary_term is not None
                else None
            ),
            "concept_registry": concept_matches,
            "word_elements": self.roots_for(term),
            "botanical_latin": BOTANICAL_LATIN_BACKGROUND,
            "etymology_review_required": True,
        }

    def analyze_glossary(self, terms: Iterable[GlossaryTerm]) -> dict[str, Any]:
        items = [self.analyze_term(term.term, glossary_term=term) for term in terms]
        return {
            "items": items,
            "count": len(items),
            "botanical_latin": BOTANICAL_LATIN_BACKGROUND,
            "word_element_release": "OC-BOTANICAL-LANGUAGE-001",
            "canonical_concept_promotion": False,
        }


def word_element_dictionary() -> list[dict[str, Any]]:
    return [asdict(item) for item in WORD_ELEMENTS]
