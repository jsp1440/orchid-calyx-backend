"""Broadened locality screen for member Matrix views (Release 1 journey 4).

Covers the Release 1 ledger's post-R1 Matrix items: coordinates written without
degree signs, grid references, plus codes, and locality/elevation/collector
vocabulary in the languages common in orchid literature. The screen must stay fail
closed without withholding ordinary Matrix morphology: a benign corpus is built from
the synthetic registry fixtures the Matrix tests actually construct.

Elevation and altitude remain withheld in every form (see the module docstring of
``app.matrix_member_views``); these tests pin that decision, and pin that a withheld
character's registry-authored state is withheld with it.
"""

from __future__ import annotations

import ast
import time
import unicodedata
from collections.abc import Callable
from pathlib import Path

import pytest

from app.matrix_member_views import (
    _ALT_TOKEN,
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
    member_candidate,
    member_explanation,
    member_registry_detail,
    screened_text,
)
from runtime.matrix_identification import Candidate
from runtime.matrix_identification_registry import (
    RegistryCharacter,
    create_registry_version,
)
from tests import test_member_matrix_identification as base
from tests.test_member_matrix_identification import PREFIX, _member

_env = base._env
registry = base.registry
client = base.client
supabase = base.supabase

pytestmark = pytest.mark.usefixtures("_env", "registry")

TESTS_DIR = Path(__file__).resolve().parent


# --- positives, one group per new pattern ---------------------------------------------

POSITIVE = {
    "dms_ascii_marks": [
        "12 34' 56\" N",
        "12 34'56\"",
        "18 55' S",
        "34' 56.7\"",
        "34'56''",
        "12 34.5'",
    ],
    "dms_unicode_marks": ["12° 34′ 56″ N", "12°34'56\"", "12 34′ 56″"],
    "dms_letters": ["12d34m", "12d 34m 56s", "18d55.5m S"],
    "hemisphere_suffix": [
        "12.345 N",
        "12.34S 45.67W",
        "12.34s 45.67w",
        "18.9S",
        "18 55 S",
        "18:55:30 S",
    ],
    "hemisphere_prefix": [
        "N 12.345",
        "N 12.34",
        "S18.91",
        "N 18 E 47",
        "S18.9, E47.5",
        "n12.34, w45.67",
    ],
    "signed_pair": ["-18.91 47.52", "−18.91 −47.52"],
    "utm": [
        "17N 630084 4833438",
        "17 N 630084mE 4833438mN",
        "630084 4833438",
        "630084mE 4833438mN",
        "UTM zone 17",
    ],
    "mgrs": ["33TWN1234567890", "33T WN 12345 67890", "4QFJ12345678", "MGRS grid"],
    "plus_code": [
        "8FVC9G8F+6X",
        "8fvc9g8f+6x",
        "8FVC0000+",
        "9G8F+6X Zurich",
        "9g8f+6x zurich",
    ],
    "geohash_labelled": ["geohash u4pruydqqvj", "Geohash: 6gkzwgjz"],
    "locality_es_pt_fr": [
        "Localidad: Río Blanco",
        "localidade tipo",
        "Localización exacta",
        "localização",
        "Coordenadas: 1 2",
        "coordonnées",
        "Fundort unbekannt",
    ],
    "elevation_es_pt": [
        "Altitud 1500",
        "altitude",
        "Elevación 1200",
        "elevacao",
        "elevação",
        "1500 msnm",
        "1500 m s.n.m.",
        "1500 m.s.n.m.",
        "1500 m snm",
        "1500 s.n.m.",
        "nivel del mar",
        "nível do mar",
    ],
    "elevation_en": [
        "1200 m a.s.l.",
        "1200 m asl",
        "1200 masl",
        "1200 asl",
        "above sea level",
        "elev. 1200",
        "alt. 1500 m",
        "alt. ca. 1500 m",
        "alt: 1500",
        "Altitudinal range",
    ],
    "abbreviations": [
        "lat. -18",
        "long. 48.42",
        "long. 48 E",
        "long: 48",
        "long.=48",
        "lon 48",
        "leg. A. Person",
        "coll. A. Person",
        "Coll. 1234",
    ],
    "collector": [
        "collected by A. Person",
        "Collected at the ridge",
        "collecting trip",
        "collection number 12",
        "collection site",
        "colectado por",
        "colector",
        "coletado por",
        "coletor",
    ],
    "site_station": [
        "Site: ridge",
        "site 12",
        "site no. 4",
        "type site",
        "study site",
        "field station",
        "Station 7",
        "station: north",
    ],
    "datum": ["GPS", "GPS12", "WGS84", "WGS 84", "datum", "NAD83", "SIRGAS 2000"],
}
POSITIVE_CASES = [(group, text) for group, items in POSITIVE.items() for text in items]


@pytest.mark.parametrize(("group", "text"), POSITIVE_CASES)
def test_screen_withholds_broadened_locality_shapes(group, text):
    assert screened_text(text) == WITHHELD, group


# --- benign: ordinary Matrix morphology ----------------------------------------------

BENIGN = [
    "Labellum length (mm)",
    "Sepal colour",
    "Lip 3-lobed",
    "Column wings present",
    "Flowering season",
    "Growth habit: epiphytic",
    "12.5–18 mm",
    "12.5-18 mm",
    "Spur 12 cm long.",
    "Spur 25–35 cm long",
    "Leaves alt., 10 cm long. 2 per node",
    "Leaves alternate",
    "L × W 12.5 × 3.4 mm",
    "W 3.5 mm",
    "S 12.5 mm",
    "Petals 2.5 × 1.2 cm",
    "Lateral sepals 12 × 4 mm",
    "2n = 40",
    "Pollinia 2, waxy",
    "Inflorescence 1–3-flowered",
    "Attachment site of the column",
    "Callus at the base of the lip",
    "Nectar spur present",
    "Leaf apex acute",
    "Pseudobulbs ovoid, 2–4 cm",
    "Angraecum sesquipedale",
    "Stanhopea tigrina Bateman ex Lindl.",
    "Masdevallia coccinea Linden ex Lindl.",
    "Dendrobium sect. Latouria",
    "Bulbophyllum Thouars",
    "Rchb.f.",
    "Collection of reviewed characters",
    "Terrestrial or lithophytic",
    "5' tall",
    # checker repair (#1679): authors, regions and measurements stay readable
    "Lindl.",
    "N.E.Br.",
    "S.Moore",
    "Hook.f.",
    "Schltr.",
    "Garay & Dunst.",
    "Angraecum sesquipedale Thouars",
    "Widespread in S. America",
    "SE Asia",
    "Leaves alt.",
    "12.50–18.30 mm",
    "Sepals 12,5 × 4,2 mm",
    "Lip 2,5–3,5 cm long",
    "col. white",
    "Altensteinia",
    "salt_tolerance",
    "alternate_leaves",
    "leaf_arrangement",
    "flower_color",
    "Ｌｉｐ ３-lobed",
    # Release 1 locality-forms slice: botanical character names and states that sit
    # next to the newly withheld forms (plant height vs. altura/Höhe, "S." as South
    # vs. an author initial, minutes as a duration) stay readable.
    "Plant height",
    "plant_height_cm",
    "Plant height 30–60 cm",
    "Stems 1.5 m tall",
    "Altura de la planta",
    "altura de la planta 30 cm",
    "altura 30 cm",
    "altura 1,5 m",
    "planta de 1,5 m de altura",
    "30 cm de altura",
    "Wuchshöhe 30 cm",
    "S. America",
    "Rchb. f.",
    "Kraenzl.",
    "Cogn.",
    "Ames & C.Schweinf.",
    "Oncidium altissimum",
    "Sobralia altissima",
    "Lip saccate, 3-lobed",
    "Darwin’s orchid",
    "Petals 12.5 × 3.5 mm",
    "Leaf 25 × 3,5 cm",
    "2n = 38",
    "Column 5 mm, winged",
    "Flowers last 30 minutes",
]


@pytest.mark.parametrize("text", BENIGN)
def test_screen_keeps_ordinary_matrix_morphology(text):
    assert screened_text(text) == text


# --- benign corpus from the real synthetic Matrix registry fixtures --------------------

REGISTRY_CONSTRUCTORS = {"RegistryCharacter", "Candidate", "create_registry_version"}
# Strings in those fixtures that genuinely carry locality, specimen or submitter
# material (the planted cases). Everything else in the corpus must pass unchanged.
KNOWN_SENSITIVE = {
    "Colour (collected at Andasibe, lat -18.91)",
    "Measured on specimen K0001 at 18°55′S",
    "PLANTED at -18.9123, 48.4211",
    "PLANTED list at -18.9123",
    "PLANTED-COLLECTOR",
    "PLANTED-GPS",
    "PLANTED-LOCALITY",
    "PLANTED-LOCALITY Andasibe",
    "PLANTED-SPECIMEN",
    "PLANTED-SPECIMEN K0001",
    "Yus (voucher PLANTED-VOUCHER)",
    "author@example.org",
    "collector",
    "decimalLatitude",
    "decimalLongitude",
    "gps",
    "latitude",
    "locality",
    "near 18°55'S 48°25'E",
    "specimen",
}


def _registry_fixture_strings() -> dict[str, set[str]]:
    """Every string literal inside a registry/character/candidate constructor call."""
    corpus: dict[str, set[str]] = {}
    for path in sorted(TESTS_DIR.glob("test_*matrix*.py")):
        if path.name == Path(__file__).name:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            func = getattr(node, "func", None)
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            if not isinstance(node, ast.Call) or name not in REGISTRY_CONSTRUCTORS:
                continue
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    corpus.setdefault(sub.value, set()).add(path.name)
    return corpus


def test_registry_fixture_corpus_is_not_newly_withheld():
    corpus = _registry_fixture_strings()
    for text in BENIGN:
        corpus.setdefault(text, set()).add("BENIGN")
    # The corpus is real: the member Matrix fixtures contribute their morphology.
    for expected in (
        "Flower color",
        "Spur length",
        "star-shaped",
        "Shape of the labellum.",
    ):
        assert expected in corpus
    assert len(corpus) >= 100
    withheld = {text for text in corpus if screened_text(text) == WITHHELD}
    newly_withheld = {text: sorted(corpus[text]) for text in withheld - KNOWN_SENSITIVE}
    assert newly_withheld == {}
    assert KNOWN_SENSITIVE & corpus.keys() <= withheld


# --- elevation / altitude character ids stay withheld ----------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "elevation_m",
        "elevation_band",
        "elevation_range",
        "altitude_band",
        "altitudinal_range",
        "Elevation band",
        "Elevation range (m)",
        "Altitude",
        "Altitud (msnm)",
        "Elevación",
    ],
)
def test_elevation_and_altitude_ids_and_labels_stay_withheld(text):
    assert screened_text(text) == WITHHELD


def test_withheld_character_also_withholds_its_candidate_state():
    row = member_explanation(
        {
            "character": "elevation_m",
            "observation": 1525,
            "candidate_state": {"min": 1520, "max": 1530},
            "status": "matched",
        }
    )
    assert row == {
        "character": WITHHELD,
        "observation": 1525,
        "candidate_state": WITHHELD,
        "status": "matched",
    }
    kept = member_explanation(
        {"character": "spur_length_mm", "candidate_state": {"min": 250, "max": 350}}
    )
    assert kept == {
        "character": "spur_length_mm",
        "candidate_state": {"min": 250, "max": 350},
    }
    shaped = member_candidate(
        {
            "taxon_id": "t:a",
            "explanations": [{"character": "altitude", "candidate_state": "montane"}],
        }
    )
    assert shaped["explanations"] == [
        {"character": WITHHELD, "candidate_state": WITHHELD}
    ]


def test_member_evaluation_withholds_elevation_character_and_its_states(
    client, supabase
):
    create_registry_version(
        registry_id="elevation",
        version="1",
        title="Elevation character fixture",
        scope={"genus": "Angraecum"},
        characters=[
            RegistryCharacter(
                "spur_length_mm", "Spur length", value_type="numeric_range"
            ),
            RegistryCharacter(
                "elevation_m", "Elevation range (m)", value_type="numeric_range"
            ),
            RegistryCharacter("elevation_band", "Elevation band"),
        ],
        candidates=[
            Candidate(
                "t:a",
                "Angraecum alpha",
                {
                    "spur_length_mm": {"min": 20, "max": 30},
                    "elevation_m": {"min": 1520, "max": 1530},
                    "elevation_band": "montane",
                },
            ),
        ],
        provenance={"source": "synthetic elevation fixture"},
        actor="registry-author@owner.example",
    )
    member = _member()
    detail = client.get(f"{PREFIX}/registry/elevation/1", headers=member).json()
    assert [c["character"] for c in detail["characters"]] == [
        "spur_length_mm",
        WITHHELD,
        WITHHELD,
    ]
    created = client.post(
        f"{PREFIX}/sessions",
        headers=member,
        json={"registry_id": "elevation", "version": "1"},
    )
    sid = created.json()["session_id"]
    for character, value in (("spur_length_mm", 25), ("elevation_m", 1525)):
        response = client.post(
            f"{PREFIX}/sessions/{sid}/observations",
            headers=member,
            json={
                "character": character,
                "value": value,
                "source": {"interface": "guided"},
            },
        )
        assert response.status_code == 200, response.text
    evaluated = client.post(
        f"{PREFIX}/sessions/{sid}/evaluate", headers=member, json={}
    )
    assert evaluated.status_code == 200, evaluated.text
    body = evaluated.text
    assert "1520" not in body and "1530" not in body
    assert "montane" not in body
    [candidate] = evaluated.json()["report"]["candidates"]
    rows = [(e["character"], e["candidate_state"]) for e in candidate["explanations"]]
    assert ("spur_length_mm", {"min": 20, "max": 30}) in rows
    assert all(state == WITHHELD for character, state in rows if character == WITHHELD)
    assert sum(1 for character, _ in rows if character == WITHHELD) >= 1


# --- linear time on 64K hostile inputs ---------------------------------------------------

SIZE = 64 * 1024


def _fill(unit: str) -> str:
    return (unit * (SIZE // len(unit) + 1))[:SIZE]


HOSTILE = [
    _fill("1"),
    _fill(" "),
    _fill("1 "),
    _fill("12 "),
    _fill("1."),
    _fill("1.1 "),
    _fill("1,1 "),
    _fill("-1.11 "),
    _fill("1'"),
    _fill("1 1'1"),
    _fill("1d1"),
    _fill("1d1 "),
    _fill("N 1"),
    _fill("N1.1 "),
    _fill("1 N"),
    _fill("1:1"),
    _fill("17N "),
    _fill("123456 "),
    _fill("33TW"),
    _fill("33TWN1"),
    _fill("2"),
    _fill("8FVC"),
    _fill("8FVC0"),
    _fill("CFGH+"),
    _fill("long. "),
    _fill("alt. "),
    _fill("m.s.n."),
    _fill("m a s "),
    _fill("site "),
    _fill("collection "),
    _fill("a" * 7 + " "),
    "1" + " " * (SIZE - 2) + "x",
    "1." + "1" * (SIZE - 3) + "x",
]
PATTERNS = {
    "sensitive_words": _SENSITIVE_WORDS,
    "coordinate_shapes": _COORDINATE_SHAPES,
    "coordinate_cased": _COORDINATE_CASED,
}


@pytest.mark.parametrize("name", sorted(PATTERNS))
@pytest.mark.parametrize("index", range(len(HOSTILE)))
def test_each_screen_pattern_is_linear_on_64k_hostile_input(name, index):
    text = HOSTILE[index]
    assert len(text) == SIZE
    started = time.perf_counter()
    PATTERNS[name].search(text)
    assert time.perf_counter() - started < 1.0


@pytest.mark.parametrize("index", range(len(HOSTILE)))
def test_screened_text_is_linear_on_64k_hostile_input(index):
    text = HOSTILE[index]
    started = time.perf_counter()
    screened_text(text, max_len=SIZE)
    assert time.perf_counter() - started < 1.0


# --- checker repair for #1679 ------------------------------------------------------------

REPAIR_POSITIVE = {
    "signed_pair_comma_decimal": [
        "-18,91; 47,52",
        "-18,91 47,52",
        "-18,9123 47,5234",
    ],
    "signed_pair_en_dash": ["–18.91 47.52", "–18.91, –47.52", "–18,91; –47,52"],
    "signed_pair_wide_separator": ["-18.91    47.52", "-18.91" + " " * 16 + "47.52"],
    "zero_width_and_bidi": [
        "-18.91\u200b 47.52",
        "-18.91\u200b47.52",
        "12.34\u200bS",
        "loc\u200bality",
        "G\u200dPS",
        "col\u00ad. J. Smith",
        "-18.91\u202e 47.52",
    ],
    "full_width": [
        "\uff11\uff12.\uff13\uff14\uff33",
        "-\uff11\uff18\uff0e\uff19\uff11 \uff14\uff17\uff0e\uff15\uff12",
        "\uff27\uff30\uff33",
        "\uff4c\uff4f\uff43\uff41\uff4c\uff49\uff54\uff59",
    ],
    "elevation_ids": [
        "elev_m",
        "alt_m",
        "elev",
        "Elev",
        "min_elev",
        "hab_alt",
        "height_asl",
        "m_asl",
        "asl_m",
        "masl_max",
        "elev-range",
        "elev.m",
        "minElev",
        "habAlt",
        "elevM",
        "elev2",
        "alt",
        "range_msnm",
    ],
    "elevation_labels": ["Elev (m)", "1500 m elev", "Elevs 1200", "Alt (m)"],
    "collector_abbreviations": [
        "col. J. Smith 1234",
        "Col. Smith",
        "col. 1234",
        "recolectado por J. Pérez",
        "Recolectado",
    ],
}
REPAIR_CASES = [
    (group, text) for group, items in REPAIR_POSITIVE.items() for text in items
]


@pytest.mark.parametrize(("group", "text"), REPAIR_CASES)
def test_screen_withholds_checker_repair_cases(group, text):
    assert screened_text(text) == WITHHELD, group


def test_screen_form_is_used_for_screening_only():
    text = "Ｌｉｐ ３-lobed"
    assert _screen_form(text) == "Lip 3-lobed"
    assert _screen_form("a\u200bb\u202ec\u00add") == "abcd"
    # The returned text is the caller's text, not the normalised screen form.
    assert screened_text(text) == text
    # NFKC rewrites the ordinal mark to "o"; it is still seen in the raw text.
    assert _screen_form("18º55 S") != "18º55 S"
    assert screened_text("18º55") == WITHHELD


def test_alt_token_is_withheld_only_in_identifier_like_strings():
    # Documented choice: "alt" is withheld as an id token, readable in prose.
    assert screened_text("hab_alt") == WITHHELD
    assert screened_text("alt") == WITHHELD
    assert screened_text("Leaves alt.") == "Leaves alt."
    assert screened_text("leaves alt., distichous") == "leaves alt., distichous"
    assert screened_text("alt. 1500 m") == WITHHELD


NEW_ELEVATION_IDS = ("elev_m", "alt_m", "min_elev", "hab_alt", "height_asl", "elevM")


@pytest.mark.parametrize("character", NEW_ELEVATION_IDS)
def test_explanation_withholds_state_for_elevation_ids(character):
    row = member_explanation(
        {"character": character, "candidate_state": {"min": 1520, "max": 1530}}
    )
    assert row == {"character": WITHHELD, "candidate_state": WITHHELD}


@pytest.mark.parametrize(
    "row",
    [
        {"candidate_state": {"min": 1520, "max": 1530}, "status": "matched"},
        {"character": None, "candidate_state": {"min": 1520, "max": 1530}},
    ],
)
def test_explanation_without_character_fails_closed(row):
    shaped = member_explanation(row)
    assert shaped["candidate_state"] == WITHHELD


def test_registry_detail_withholds_elevation_ids_and_never_returns_states():
    record = {
        "registry_id": "r",
        "version": "1",
        "characters": [
            {"character": character, "label": "x", "value_type": "numeric_range"}
            for character in NEW_ELEVATION_IDS
        ]
        + [{"character": "spur_length_mm", "label": "Spur length"}],
        "candidates": [
            {"taxon_id": "t:a", "states": {"elev_m": {"min": 1520, "max": 1530}}}
        ],
    }
    detail = member_registry_detail(record)
    assert [c["character"] for c in detail["characters"]] == [WITHHELD] * len(
        NEW_ELEVATION_IDS
    ) + ["spur_length_mm"]
    assert "candidates" not in detail
    assert "1520" not in repr(detail)


def test_member_evaluation_withholds_abbreviated_elevation_ids(client, supabase):
    states = {character: {"min": 1520, "max": 1530} for character in NEW_ELEVATION_IDS}
    create_registry_version(
        registry_id="elevation-abbrev",
        version="1",
        title="Abbreviated elevation character fixture",
        scope={"genus": "Angraecum"},
        characters=[
            RegistryCharacter(
                "spur_length_mm", "Spur length", value_type="numeric_range"
            )
        ]
        + [
            RegistryCharacter(character, "Range (m)", value_type="numeric_range")
            for character in NEW_ELEVATION_IDS
        ],
        candidates=[
            Candidate(
                "t:a",
                "Angraecum alpha",
                {"spur_length_mm": {"min": 20, "max": 30}, **states},
            )
        ],
        provenance={"source": "synthetic elevation fixture"},
        actor="registry-author@owner.example",
    )
    member = _member()
    detail = client.get(f"{PREFIX}/registry/elevation-abbrev/1", headers=member)
    assert [c["character"] for c in detail.json()["characters"]] == [
        "spur_length_mm"
    ] + [WITHHELD] * len(NEW_ELEVATION_IDS)
    sid = client.post(
        f"{PREFIX}/sessions",
        headers=member,
        json={"registry_id": "elevation-abbrev", "version": "1"},
    ).json()["session_id"]
    for character, value in (
        ("spur_length_mm", 25),
        ("elev_m", 1525),
        ("hab_alt", 1525),
    ):
        response = client.post(
            f"{PREFIX}/sessions/{sid}/observations",
            headers=member,
            json={
                "character": character,
                "value": value,
                "source": {"interface": "guided"},
            },
        )
        assert response.status_code == 200, response.text
    evaluated = client.post(
        f"{PREFIX}/sessions/{sid}/evaluate", headers=member, json={}
    )
    assert evaluated.status_code == 200, evaluated.text
    assert "1520" not in evaluated.text and "1530" not in evaluated.text
    for character in NEW_ELEVATION_IDS:
        assert character not in evaluated.text
    [candidate] = evaluated.json()["report"]["candidates"]
    rows = [(e["character"], e["candidate_state"]) for e in candidate["explanations"]]
    assert ("spur_length_mm", {"min": 20, "max": 30}) in rows
    assert all(state == WITHHELD for character, state in rows if character == WITHHELD)


REPAIR_HOSTILE = [
    _fill("-1,11 "),
    _fill("-1.11" + " " * 15),
    _fill("–1.11 "),
    _fill("-1,1"),
    _fill("a_"),
    _fill("aA"),
    _fill("a1"),
    _fill("_"),
    _fill("elevx_"),
    _fill("altx"),
    _fill("col. "),
    _fill("col. J"),
    _fill("Col."),
    _fill("recolec"),
    _fill("\u200b"),
    _fill("1\u200b"),
    _fill("\uff11"),
    _fill("\uff11 \uff2e"),
    _fill("º"),
    _fill("Alt ("),
]
REPAIR_PATTERNS = {
    **PATTERNS,
    "token_split": _TOKEN_SPLIT,
    "elevation_tokens": _ELEVATION_TOKENS,
    "alt_token": _ALT_TOKEN,
}


@pytest.mark.parametrize("name", sorted(REPAIR_PATTERNS))
@pytest.mark.parametrize("index", range(len(REPAIR_HOSTILE)))
def test_each_repaired_pattern_is_linear_on_64k_hostile_input(name, index):
    text = REPAIR_HOSTILE[index]
    assert len(text) == SIZE
    started = time.perf_counter()
    REPAIR_PATTERNS[name].search(text)
    assert time.perf_counter() - started < 1.0


@pytest.mark.parametrize("index", range(len(REPAIR_HOSTILE)))
def test_repaired_screen_is_linear_on_64k_hostile_input(index):
    text = REPAIR_HOSTILE[index]
    started = time.perf_counter()
    screened_text(text, max_len=SIZE)
    _TOKEN_SPLIT.sub(" ", text)
    assert time.perf_counter() - started < 1.0


# ======================================================================================
# Release 1 ledger locality forms (moved here so OC Critical Suites runs them).
#
# Locality forms the member Matrix screen still let through (Release 1 ledger).
#
# ``app.matrix_member_views.screened_text`` withholds locality from Matrix responses
# shown to members. The Release 1 ledger lists written forms that still got through:
# degrees/minutes spelled out in Spanish, Portuguese and French, a lower-case
# hemisphere after a bare number, ``18d55mS``, lower-case MGRS, the modifier
# apostrophe, French "au-dessus du niveau de la mer", specimen words, run-together
# elevation ids, ``alt m``/``Alt [m]``, German Höhe, Spanish altura with an elevation
# unit, combining marks and Cyrillic homoglyphs. Each one is pinned here.
#
# Spanish ``altura`` also means plant height, so it is withheld only with an elevation
# context (a metre value of three or more digits, ``s.n.m.``); plant heights stay
# readable -- see the benign corpus above.
#
# Not handled (recorded as follow-ups, not silently dropped): an unlabelled geohash
# (``u4pruydqqvj``) and a single comma-decimal value (``-18,91``, ``18,9123``). Neither
# can be told apart from identifiers and European-style measurements without a
# false-positive rate on morphology that has not been measured; the labelled geohash
# and paired comma-decimal coordinates are already withheld.
#
# All strings are synthetic.
# ======================================================================================


def _nfd(text: str) -> str:
    return unicodedata.normalize("NFD", text)


LF_POSITIVE = {
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
LF_POSITIVE_CASES = [
    (group, text) for group, items in LF_POSITIVE.items() for text in items
]


@pytest.mark.parametrize(("group", "text"), LF_POSITIVE_CASES)
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
LF_SIZE = 64 * 1024
BOUND_SECONDS = 1.0
FLOOR_SECONDS = 0.05  # timer noise under parallel CI load


def _lf_fill(unit: str, size: int) -> str:
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
    small, large = _lf_fill(unit, SMALL), _lf_fill(unit, LF_SIZE)
    assert len(large) == LF_SIZE
    t_small = _best_of(lambda: screened_text(small, max_len=LF_SIZE))
    t_large = _best_of(lambda: screened_text(large, max_len=LF_SIZE))
    assert t_large < BOUND_SECONDS, f"{unit!r}: {t_large:.3f}s"
    assert t_large < 8 * max(t_small, FLOOR_SECONDS), (
        f"{unit!r}: {t_small:.4f}s -> {t_large:.4f}s for 4x input"
    )


LF_PATTERNS = {
    "sensitive_words": _SENSITIVE_WORDS,
    "coordinate_shapes": _COORDINATE_SHAPES,
    "coordinate_cased": _COORDINATE_CASED,
    "coordinate_lower": _COORDINATE_LOWER,
    "elevation_tokens": _ELEVATION_TOKENS,
    "elevation_compound": _ELEVATION_COMPOUND,
}


@pytest.mark.parametrize("name", sorted(LF_PATTERNS))
@pytest.mark.parametrize("unit", HOSTILE_UNITS)
def test_each_new_pattern_is_linear_on_64k_hostile_input(name, unit):
    pattern = LF_PATTERNS[name]
    small, large = _lf_fill(unit, SMALL), _lf_fill(unit, LF_SIZE)
    t_small = _best_of(lambda: pattern.search(small))
    t_large = _best_of(lambda: pattern.search(large))
    assert t_large < BOUND_SECONDS, f"{name} {unit!r}: {t_large:.3f}s"
    assert t_large < 8 * max(t_small, FLOOR_SECONDS)


def test_token_split_and_folds_are_linear_on_64k_input():
    text = _lf_fill("aA1_\u0430e\u0301\u02bc", LF_SIZE)
    assert _best_of(lambda: _TOKEN_SPLIT.sub(" ", text)) < BOUND_SECONDS
    assert _best_of(lambda: _strip_marks(_screen_form(text))) < BOUND_SECONDS


# --- checker repair round 1 (#1708) ------------------------------------------------------

LF_REPAIR_POSITIVE = {
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
LF_REPAIR_CASES = [
    (group, text) for group, items in LF_REPAIR_POSITIVE.items() for text in items
]


@pytest.mark.parametrize(("group", "text"), LF_REPAIR_CASES)
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
    small, large = _lf_fill(unit, SMALL), _lf_fill(unit, LF_SIZE)
    t_small = _best_of(lambda: screened_text(small, max_len=LF_SIZE))
    t_large = _best_of(lambda: screened_text(large, max_len=LF_SIZE))
    assert t_large < BOUND_SECONDS, f"{unit!r}: {t_large:.3f}s"
    assert t_large < 8 * max(t_small, FLOOR_SECONDS)


@pytest.mark.parametrize("unit", ROUND1_HOSTILE_UNITS)
def test_mgrs_and_compound_patterns_are_linear_on_round1_input(unit):
    small, large = _lf_fill(unit, SMALL), _lf_fill(unit, LF_SIZE)
    for pattern in (_MGRS, _ELEVATION_COMPOUND, _SENSITIVE_WORDS, _COORDINATE_SHAPES):
        t_small = _best_of(lambda p=pattern: p.search(small))
        t_large = _best_of(lambda p=pattern: p.search(large))
        assert t_large < BOUND_SECONDS
        assert t_large < 8 * max(t_small, FLOOR_SECONDS)
