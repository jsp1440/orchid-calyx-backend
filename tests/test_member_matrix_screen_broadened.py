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
from pathlib import Path

import pytest

from app.matrix_member_views import (
    _COORDINATE_CASED,
    _COORDINATE_SHAPES,
    _SENSITIVE_WORDS,
    WITHHELD,
    member_candidate,
    member_explanation,
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
        "18.9S",
        "18 55 S",
        "18:55:30 S",
    ],
    "hemisphere_prefix": ["N 12.345", "N 12.34", "S18.91", "N 18 E 47", "S18.9, E47.5"],
    "signed_pair": ["-18.91 47.52", "−18.91 −47.52"],
    "utm": [
        "17N 630084 4833438",
        "17 N 630084mE 4833438mN",
        "630084 4833438",
        "630084mE 4833438mN",
        "UTM zone 17",
    ],
    "mgrs": ["33TWN1234567890", "33T WN 12345 67890", "4QFJ12345678", "MGRS grid"],
    "plus_code": ["8FVC9G8F+6X", "8fvc9g8f+6x", "8FVC0000+", "9G8F+6X Zurich"],
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
