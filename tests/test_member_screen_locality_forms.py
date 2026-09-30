"""Locality forms the member Matrix screen still let through (Release 1 ledger).

``app.matrix_member_views.screened_text`` withholds locality from Matrix responses
shown to members. The Release 1 ledger lists written forms that still got through:
degrees/minutes spelled out in Spanish, Portuguese and French, a lower-case
hemisphere after a bare number, ``18d55mS``, lower-case MGRS, the modifier
apostrophe, French "au-dessus du niveau de la mer", specimen words, run-together
elevation ids, ``alt m``/``Alt [m]``, German Höhe, Spanish altura with an elevation
unit, combining marks and Cyrillic homoglyphs. Each one is pinned here.

Spanish ``altura`` also means plant height, so it is withheld only with an elevation
context (a metre value of three or more digits, ``s.n.m.``); plant heights stay
readable -- see the benign corpus in ``test_member_matrix_screen_broadened.py``.

Not handled (recorded as follow-ups, not silently dropped): an unlabelled geohash
(``u4pruydqqvj``) and a single comma-decimal value (``-18,91``, ``18,9123``). Neither
can be told apart from identifiers and European-style measurements without a
false-positive rate on morphology that has not been measured; the labelled geohash
and paired comma-decimal coordinates are already withheld.

All strings are synthetic.
"""

from __future__ import annotations

import time
import unicodedata
from collections.abc import Callable

import pytest

from app.matrix_member_views import (
    _COORDINATE_CASED,
    _COORDINATE_LOWER,
    _COORDINATE_SHAPES,
    _ELEVATION_COMPOUND,
    _ELEVATION_TOKENS,
    _MGRS,
    _SENSITIVE_WORDS,
    _TOKEN_SPLIT,
    WITHHELD,
    _screen_form,
    _strip_marks,
    member_explanation,
    member_registry_detail,
    screened_text,
)


def _nfd(text: str) -> str:
    return unicodedata.normalize("NFD", text)


POSITIVE = {
    "dms_words_es_pt_fr": [
        "18 grados 55 minutos S",
        "18 grados 55 minutos sur",
        "18 grados",
        "18,5 grados S",
        "18 graus 55 minutos S",
        "18 graus",
        "18 degrés 55 minutes sud",
        "18 degrés",
        "18 degres",
        "55 minutos S",
        "55 minutes sud",
        "55 minutos 30 segundos oeste",
        "47 minutes E",
    ],
    "lowercase_hemisphere": [
        "18.9s",
        "18.9 s",
        "18,9s",
        "18 55 s",
        "18:55 s",
        "18 55 30 s",
        "12.34n",
        "47.52e",
        "47.52 w",
    ],
    "dms_letters_hemisphere": ["18d55mS", "18d55ms", "18d55m12sS", "18d 55m S"],
    "mgrs_lowercase": ["33twn1234567890", "33t wn 12345 67890", "4qfj12345678"],
    "modifier_apostrophe": [
        "12 34\u02bc 56\u02bc\u02bc",
        "18 55\u02bc S",
        "34\u02bc56\u02ba",
        "12 34\u2019 56\u201d",
        "34\u02b9 56\u02ba",
    ],
    "sea_level_fr_it_de": [
        "1500 m au-dessus du niveau de la mer",
        "au-dessus du niveau de la mer",
        "niveau de la mer",
        "1500 m sul livello del mare",
        "1500 m über dem Meeresspiegel",
    ],
    "specimen_words": [
        "herbier",
        "Herbier du Muséum",
        "exsiccata",
        "exsiccatae",
        "ejemplar",
        "Ejemplar de referencia",
        "spécimen",
        "espécimen",
        "espécime",
    ],
    "run_together_ids": [
        "elevm",
        "altm",
        "aslm",
        "elevft",
        "ELEVmax",
        "ALTmin",
        "ASLrange",
        "elevmin_m",
        "habitat_altmax",
        "masl_range",
        "msnmmax",
    ],
    "alt_unit": ["alt m", "Alt [m]", "alt\tm", "alt. ft", "Alt [ft]", "alt  metres"],
    "hoehe": [
        "hoehe",
        "höhe",
        "Höhe",
        "Höhe 1500 m",
        "hoehe_m",
        "Höhenlage",
        "Meereshöhe",
        "Seehöhe",
    ],
    "altura_elevation": [
        "altura 1500 m",
        "Altura: 1500 m",
        "altura ca. 1500 m",
        "altura 1.500 m",
        "altura 1200-1500 m",
        "altura 1500 msnm",
        "altura 1500 metros",
        "altura s.n.m.",
        "altura sobre el nivel del mar",
        "a 1500 m de altura",
        "1.500 metros de altura",
    ],
    "combining_marks": [
        _nfd("élev_m"),
        _nfd("élévation"),
        _nfd("Höhe"),
        _nfd("höhe 1500 m"),
        _nfd("localización"),
        "e\u0301lev_m",
        "ele\u0301v",
    ],
    "cyrillic_homoglyphs": [
        "l\u0430titude",  # Cyrillic a
        "loc\u0430lity",
        "\u0435levation",  # Cyrillic ie
        "\u0435lev_m",
        "\u0441ollector",  # Cyrillic es
        "sp\u0435\u0441imen",
        "\u0430lt_m",
        "G\u0420S",  # Cyrillic Er
        "1500 \u041csnm",  # Cyrillic Em
        "l\u03bfcality",  # Greek omicron
    ],
}
POSITIVE_CASES = [(group, text) for group, items in POSITIVE.items() for text in items]


@pytest.mark.parametrize(("group", "text"), POSITIVE_CASES)
def test_screen_withholds_release1_locality_forms(group, text):
    assert screened_text(text) == WITHHELD, (group, text)


# Readable text next to the new forms, beyond the shared benign corpus.
READABLE = [
    "Flowers resupinate",
    "Lindl.",
    "Rchb.f.",
    "S. America",
    "altura de la planta 30 cm",
    "Altura de la planta (cm)",
    "altura 1,5 m",
    "Altensteinia",
    "Altmann",
    "alternate",
    "leaves alt. many-flowered",
    "hohe Pflanze",
    "Lip 12.5 mm, apex acute",
    "S 12.5 mm",
    "W 3.5 mm",
    "2n = 40",
    "12d34mm",
    "Sepals 3 mm",
    "Lip minutely papillose",
    "Flowers open for 30 minutes",
    "Darwin\u02bcs orchid",
    "Lip \u2018saccate\u2019",
    "Petals \u201cfalcate\u201d",
    "Stelis 3 mm",
    "\u041e\u0440\u0445\u0438\u0434\u0435\u044f",  # Cyrillic word, no locality word
]


@pytest.mark.parametrize("text", READABLE)
def test_screen_keeps_neighbouring_morphology_readable(text):
    assert screened_text(text) == text


def test_screen_forms_are_used_for_screening_only():
    assert _screen_form("loc\u0430lity") == "locality"
    assert _screen_form("12 34\u02bc") == "12 34'"
    assert _strip_marks(_nfd("élev_m")) == "elev_m"
    # The member sees the caller's text, never a folded form.
    assert screened_text("Darwin\u02bcs orchid") == "Darwin\u02bcs orchid"
    assert screened_text(_nfd("Lip rosé")) == _nfd("Lip rosé")


@pytest.mark.parametrize(
    "character",
    ["elevm", "ELEVmax", "altm", "\u0435lev_m", _nfd("élev_m"), "hoehe_m"],
)
def test_explanation_withholds_state_for_new_elevation_ids(character):
    row = member_explanation(
        {"character": character, "candidate_state": {"min": 1520, "max": 1530}}
    )
    assert row == {"character": WITHHELD, "candidate_state": WITHHELD}


def test_registry_detail_withholds_new_forms_in_labels_and_descriptions():
    detail = member_registry_detail(
        {
            "registry_id": "r",
            "version": "1",
            "characters": [
                {"character": "ELEVmax", "label": "Range"},
                {"character": "altura_band", "label": "altura 1500 m"},
                {
                    "character": "lip_shape",
                    "label": "Lip shape",
                    "description": "Seen at 18 grados 55 minutos S",
                },
                {"character": "plant_height_cm", "label": "Altura de la planta"},
            ],
        }
    )
    assert [
        (c["character"], c["label"], c.get("description")) for c in detail["characters"]
    ] == [
        (WITHHELD, "Range", None),
        ("altura_band", WITHHELD, None),
        ("lip_shape", "Lip shape", WITHHELD),
        ("plant_height_cm", "Altura de la planta", None),
    ]


# --- linear time on 64K hostile inputs ----------------------------------------------

SMALL = 16 * 1024
SIZE = 64 * 1024
BOUND_SECONDS = 1.0
FLOOR_SECONDS = 0.05  # timer noise under parallel CI load


def _fill(unit: str, size: int) -> str:
    return (unit * (size // len(unit) + 1))[:size]


def _best_of(fn: Callable[[], object], runs: int = 5) -> float:
    best = float("inf")
    for _ in range(runs):
        started = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - started)
    return best


HOSTILE_UNITS = [
    "1 grados ",
    "1 grado",
    "1,1 degr",
    "1 minutos ",
    "1 minutos 1 segundos ",
    "1 minute",
    "1.1 ",
    "1 1 ",
    "1:1 ",
    "1.1s1",
    "1d1m1",
    "1d1m1s",
    "1d 1m ",
    "33tw",
    "33twn1",
    "1c",
    "altura 1",
    "altura 111 ",
    "altura 1.111 a ",
    "111 m de ",
    "111 metros de altur",
    "hoeh",
    "höh",
    "alt [",
    "alt m",
    "alt  ",
    "elevmx",
    "altmi",
    "ASLr",
    "niveau de la ",
    "au-dessus du ",
    "herbie",
    "exsicca",
    "e\u0301",
    "\u0301",
    "\u0430",
    "l\u0430t",
    "\u02bc",
    "1 1\u02bc",
    "1\u02bc1\u02ba",
]


@pytest.mark.parametrize("unit", HOSTILE_UNITS)
def test_screened_text_is_bounded_and_linear_on_64k_hostile_input(unit):
    small, large = _fill(unit, SMALL), _fill(unit, SIZE)
    assert len(large) == SIZE
    t_small = _best_of(lambda: screened_text(small, max_len=SIZE))
    t_large = _best_of(lambda: screened_text(large, max_len=SIZE))
    assert t_large < BOUND_SECONDS, f"{unit!r}: {t_large:.3f}s"
    assert t_large < 8 * max(t_small, FLOOR_SECONDS), (
        f"{unit!r}: {t_small:.4f}s -> {t_large:.4f}s for 4x input"
    )


PATTERNS = {
    "sensitive_words": _SENSITIVE_WORDS,
    "coordinate_shapes": _COORDINATE_SHAPES,
    "coordinate_cased": _COORDINATE_CASED,
    "coordinate_lower": _COORDINATE_LOWER,
    "elevation_tokens": _ELEVATION_TOKENS,
    "elevation_compound": _ELEVATION_COMPOUND,
}


@pytest.mark.parametrize("name", sorted(PATTERNS))
@pytest.mark.parametrize("unit", HOSTILE_UNITS)
def test_each_new_pattern_is_linear_on_64k_hostile_input(name, unit):
    pattern = PATTERNS[name]
    small, large = _fill(unit, SMALL), _fill(unit, SIZE)
    t_small = _best_of(lambda: pattern.search(small))
    t_large = _best_of(lambda: pattern.search(large))
    assert t_large < BOUND_SECONDS, f"{name} {unit!r}: {t_large:.3f}s"
    assert t_large < 8 * max(t_small, FLOOR_SECONDS)


def test_token_split_and_folds_are_linear_on_64k_input():
    text = _fill("aA1_\u0430e\u0301\u02bc", SIZE)
    assert _best_of(lambda: _TOKEN_SPLIT.sub(" ", text)) < BOUND_SECONDS
    assert _best_of(lambda: _strip_marks(_screen_form(text))) < BOUND_SECONDS


# --- checker repair round 1 (#1708) ------------------------------------------------------

REPAIR_POSITIVE = {
    "accented_lookalikes": [
        "l\u04e7cality",  # Cyrillic o with diaeresis
        "\u0450levation",  # Cyrillic ie with grave
        "H\u04e7he 1200",
        "l\u03cccality",  # Greek omicron with tonos
        "\u0435\u0301lev_m",  # Cyrillic ie + combining acute
        "lo\u03f2ality",  # Greek lunate sigma
        "\u03f2ollector",
        "sp\u0435\u03f2imen",
    ],
    "mgrs_mixed_case_and_spacing": [
        "33tWN1234567890",
        "33Twn1234567890",
        "33t  wn 12345 67890",
        "33T WN  12345  67890",
        "33tWn 12345 67890",
    ],
    "run_together_ids": [
        "hoeheMax",
        "minHöhe",
        "maxHoehe",
        "höhem",
        "elevmaximum",
        "elevmedian",
        "elevmsl",
        "elevmasl",
        "altmsl",
        "minalt",
        "maxelev_m",
        "Höhe_max",
    ],
    "near_misses_coordinates": [
        "18.9  s",
        "18.9   S",
        "18d55'S",
        "18d55min S",
        "18d 55 min S",
        "18 d 55 m S",
        "12 34  56\u2033",
        "34'  56\"",
    ],
    "near_misses_alt": [
        "alt   m",
        "alt: m",
        "Alt (metros)",
        "Alt [mts]",
        "alt = ft",
        "Alt ( m )",
        "alt   1500",
    ],
    "near_misses_altura": [
        "altura entre 1500 y 2000 m",
        "altura 1 500 m",
        "altura ca 1500 m",
        "altura de ca. 1500 msnm",
        "altura desde 1200 hasta 1500 m",
        "altura 1500 m.s.n.m.",
    ],
    "near_misses_words": [
        "exsicata",
        "au\u2011dessus du niveau de la mer",  # non-breaking hyphen
        "au\u2010dessus du niveau",
        "au \u2014 dessus du niveau",
        "niveau moyen de la mer",
        "nivel medio del mar",
        "livello medio del mare",
    ],
    "prime_lookalikes": [
        "12 34\ua78c 56\ua78c\ua78c",
        "18 55\u201b S",
        "18 55\u05f3 S",
        "34\u05f3 56\u05f4",
        "34\u2035 56\u2036",
    ],
    "invisible_fillers": [
        "loc\u3164ality",
        "lat\uffa0itude",
        "loc\u2800ality",
        "e\u115flev_m",
        "G\u17b4PS",
    ],
}
REPAIR_CASES = [
    (group, text) for group, items in REPAIR_POSITIVE.items() for text in items
]


@pytest.mark.parametrize(("group", "text"), REPAIR_CASES)
def test_screen_withholds_checker_round1_bypasses(group, text):
    assert screened_text(text) == WITHHELD, (group, text)


REPAIR_READABLE = [
    "\u0441o\u043f\u0442\u0435\u043f\u0456do",  # folds to "coptenido": no locality word
    "Lip 3\u20135 mm",
    "Petals \u2014 white",
    "12.5\u201318 mm",
    "Sepals 2,5\u20133,5 cm",
    "5th ed 1234 5678",
    "15mm 12 34",
    "2nd pp 12 34",
    "3rd ed 1990 2000",
    "altura 1,5 m",
    "altura de 150 cm",
    "altura 300 mm",
    "leaves alt. many-flowered",
    "Altmann",
    "hohe Pflanze",
    "Petals 12.5 × 3.5 mm",
    "12d34mm",
    "Lip \u2018saccate\u2019",
    "Flowers open for 30 minutes",
    "median lip length",
    "Column 5 mm, winged",
]


@pytest.mark.parametrize("text", REPAIR_READABLE)
def test_screen_keeps_morphology_readable_after_round1(text):
    assert screened_text(text) == text


def test_fold_runs_before_and_after_decomposition():
    assert _screen_form("H\u04e7he") == "Höhe"
    assert _strip_marks(_screen_form("l\u03cccality")) == "locality"
    assert _screen_form("au\u2011dessus") == "au-dessus"
    assert _screen_form("loc\u3164ality") == "locality"
    assert _screen_form("18 55\ua78c") == "18 55'"


ROUND1_HOSTILE_UNITS = [
    "33t  w",
    "33tW  n1 ",
    "1d  1 min ",
    "1d1'",
    "1.1  ",
    "alt   (",
    "alt: ",
    "altura entre 111 y ",
    "altura 1 111 ",
    "altura ca ",
    "niveau moyen de la ",
    "au\u2011",
    "hoeheM",
    "minHöh",
    "elevma",
    "elevmsx",
    "l\u04e7c",
    "\u03f2",
    "\u3164",
    "\ua78c1 ",
]


@pytest.mark.parametrize("unit", ROUND1_HOSTILE_UNITS)
def test_screened_text_is_linear_on_round1_hostile_input(unit):
    small, large = _fill(unit, SMALL), _fill(unit, SIZE)
    t_small = _best_of(lambda: screened_text(small, max_len=SIZE))
    t_large = _best_of(lambda: screened_text(large, max_len=SIZE))
    assert t_large < BOUND_SECONDS, f"{unit!r}: {t_large:.3f}s"
    assert t_large < 8 * max(t_small, FLOOR_SECONDS)


@pytest.mark.parametrize("unit", ROUND1_HOSTILE_UNITS)
def test_mgrs_and_compound_patterns_are_linear_on_round1_input(unit):
    small, large = _fill(unit, SMALL), _fill(unit, SIZE)
    for pattern in (_MGRS, _ELEVATION_COMPOUND, _SENSITIVE_WORDS, _COORDINATE_SHAPES):
        t_small = _best_of(lambda p=pattern: p.search(small))
        t_large = _best_of(lambda p=pattern: p.search(large))
        assert t_large < BOUND_SECONDS
        assert t_large < 8 * max(t_small, FLOOR_SECONDS)
