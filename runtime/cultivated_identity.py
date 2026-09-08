"""Fail-closed cultivated orchid identity resolution.

Collection labels preserve the grower's full cultivated identity.  This module only
derives a species lookup when the label itself makes that relationship
scientifically defensible; it never rewrites the stored identity or chooses a
parent/nearest taxon for an interspecific cross.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MAX_IDENTITY_CHARACTERS = 240
_UNSAFE_PUNCTUATION = re.compile(r"[<>{}\\\\]")
_HYBRID_SEPARATOR = re.compile(r"\\s(?:×|x|X)\\s")
_CULTIVAR_EPITHET = re.compile(r"""\\s*(?:'[^']*'|‘[^’]*’|"[^"]*")\\s*""")
_GENUS = re.compile(r"^[A-Z][a-z-]+$")
_SPECIES_EPITHET = re.compile(r"^[a-z][a-z-]+$")

_GENUS_ABBREVIATIONS = {
    "phrag.": "Phragmipedium",
    "phrag": "Phragmipedium",
    "paph.": "Paphiopedilum",
    "paph": "Paphiopedilum",
    "phal.": "Phalaenopsis",
    "phal": "Phalaenopsis",
    "catt.": "Cattleya",
    "c.": "Cattleya",
    "den.": "Dendrobium",
    "onc.": "Oncidium",
    "masd.": "Masdevallia",
    "bulb.": "Bulbophyllum",
}


@dataclass(frozen=True)
class CultivatedIdentity:
    cultivated: str
    species: str | None
    genus: str | None
    relationship: str
    reason: str | None = None


@dataclass(frozen=True)
class _Parent:
    species: str | None
    missing_genus: str | None = None
    ambiguous_capital: str | None = None


def _expand_genus(word: str) -> str:
    return _GENUS_ABBREVIATIONS.get(word.lower(), word)


def _one_parent(
    part: str,
    *,
    context_genus: str | None,
    context_species: str | None,
) -> _Parent:
    words = _CULTIVAR_EPITHET.sub(" ", part).strip().split()
    if not words:
        return _Parent(context_species)

    if len(words) == 1:
        only = words[0]
        if _SPECIES_EPITHET.fullmatch(only):
            if context_genus:
                return _Parent(f"{context_genus} {only}")
            return _Parent(None, missing_genus=only)
        return _Parent(None)

    if len(words) != 2:
        return _Parent(None)

    genus = _expand_genus(words[0])
    epithet = words[1]
    if not _GENUS.fullmatch(genus):
        return _Parent(None)
    if not _SPECIES_EPITHET.fullmatch(epithet):
        if _GENUS.fullmatch(epithet):
            return _Parent(None, ambiguous_capital=epithet)
        return _Parent(None)
    return _Parent(f"{genus} {epithet}")


def _cross_parts(cultivated: str) -> tuple[list[str], str | None]:
    bracketed = re.fullmatch(r"(.*?)\\s*\\(([^()]+)\\)\\s*", cultivated)
    if not bracketed or not _HYBRID_SEPARATOR.search(bracketed.group(2)):
        return [part.strip() for part in _HYBRID_SEPARATOR.split(cultivated)], None

    prefix = bracketed.group(1).strip()
    inner = bracketed.group(2)
    sides = [part.strip() for part in _HYBRID_SEPARATOR.split(inner) if part.strip()]
    if prefix and all(not _CULTIVAR_EPITHET.sub(" ", side).strip() for side in sides):
        return [f"{prefix} {side}" for side in sides], None

    first = _expand_genus(prefix.split()[0]) if prefix else ""
    return sides, first if _GENUS.fullmatch(first) else None


def resolve_cultivated_identity(stored: str | None) -> CultivatedIdentity | None:
    """Return a defensible species binding, or an explicit non-binding result."""

    cultivated = " ".join((stored or "").split())
    if (
        not cultivated
        or len(cultivated) > MAX_IDENTITY_CHARACTERS
        or any(ord(character) <= 31 or ord(character) == 127 for character in cultivated)
        or _UNSAFE_PUNCTUATION.search(cultivated)
    ):
        return None

    parts, seed_genus = _cross_parts(cultivated)

    def missing_genus(epithet: str) -> CultivatedIdentity:
        return CultivatedIdentity(
            cultivated,
            None,
            None,
            "none",
            f'No genus is written, so "{epithet}" cannot be matched to a species.',
        )

    def ambiguous_capital(word: str) -> CultivatedIdentity:
        return CultivatedIdentity(
            cultivated,
            None,
            None,
            "none",
            f'"{word}" is capitalised, so it may be a grex rather than a species.',
        )

    if len(parts) == 1:
        parent = _one_parent(
            parts[0],
            context_genus=seed_genus,
            context_species=None,
        )
        if parent.missing_genus:
            return missing_genus(parent.missing_genus)
        if parent.ambiguous_capital:
            return ambiguous_capital(parent.ambiguous_capital)
        if not parent.species:
            return CultivatedIdentity(
                cultivated,
                None,
                None,
                "none",
                "This identity is a genus or grex, not a defensible species binding.",
            )
        relationship = (
            "cultivar_of_species" if _CULTIVAR_EPITHET.search(cultivated) else "species"
        )
        return CultivatedIdentity(
            cultivated,
            parent.species,
            parent.species.split()[0],
            relationship,
        )

    if len(parts) != 2:
        return CultivatedIdentity(
            cultivated,
            None,
            None,
            "none",
            "A cross of more than two parents has no single species to look up.",
        )

    left_result = _one_parent(
        parts[0],
        context_genus=seed_genus,
        context_species=None,
    )
    if left_result.missing_genus:
        return missing_genus(left_result.missing_genus)
    if left_result.ambiguous_capital:
        return ambiguous_capital(left_result.ambiguous_capital)

    left = left_result.species
    right_result = _one_parent(
        parts[1],
        context_genus=left.split()[0] if left else seed_genus,
        context_species=left,
    )
    if right_result.missing_genus:
        return missing_genus(right_result.missing_genus)
    if right_result.ambiguous_capital:
        return ambiguous_capital(right_result.ambiguous_capital)

    right = right_result.species
    if not left or not right:
        return CultivatedIdentity(
            cultivated,
            None,
            None,
            "none",
            "At least one parent is not a species; no species lookup is defensible.",
        )
    if left != right:
        same_genus = left.split()[0] == right.split()[0]
        return CultivatedIdentity(
            cultivated,
            None,
            left.split()[0] if same_genus else None,
            "none",
            f"This is a cross between {left} and {right}; neither parent may be substituted.",
        )

    return CultivatedIdentity(
        cultivated,
        left,
        left.split()[0],
        "cross_within_species",
    )
