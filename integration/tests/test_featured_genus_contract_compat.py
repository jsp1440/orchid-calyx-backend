"""Featured Genus contract compatibility: Calyx #1803 backend x Frontend #914.

Verifies, locally and without any provider, network, or database, that:

  1. The real Calyx `featured-genus-profile/v1` producer output
     (`build_featured_genus_profile`, PR #1803 head 4b8e32a6) is ACCEPTED by
     the frontend read model's validation rules (`normalizeFeaturedGenusProfile`,
     frontend PR #914 head df9f81a2, src/lib/featuredGenusProfile.ts).
  2. The real `featured-genus-selection/v1` producer output
     (`select_featured_genus`) is ACCEPTED by `normalizeFeaturedGenusSelection`.
  3. Backend and frontend genus-boundary validators agree exactly
     (backend `canonical_genus` vs frontend `normalizeFeaturedTaxonGenus`,
     src/lib/featuredTaxonContinuum.ts @ aa6117b9).
  4. Backend DEFAULT_ROTATION_CANDIDATES is identical to the frontend
     FEATURED_GENERA rotation list (src/lib/featuredGenus.ts @ eb33fa63),
     and the backend window math `floor(epoch_s / 43200) % n` equals the
     frontend `floor(epoch_ms / 43200000) % n` for every sampled epoch.
  5. Degraded evidence states (unknown / unavailable / invalid_genus) survive
     the frontend contract exactly as the backend emits them.

The frontend normalizers are ported to Python below, rule for rule, from
frontend #914 `src/lib/featuredGenusProfile.ts`; the port is a verification
oracle, not a new consumer. Backend code is imported from a byte-verified
checkout of the #1803 head (OC_FEATURED_GENUS_ROOT); tests skip when absent.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
CALYX_ROOT = Path(os.environ.get("OC_CALYX_ROOT", HERE.parents[2]))
FG_ROOT = Path(
    os.environ.get("OC_FEATURED_GENUS_ROOT", CALYX_ROOT.parent / "calyx-1803")
)

fg_missing = pytest.mark.skipif(
    not (FG_ROOT / "app" / "featured_genus" / "profile.py").is_file(),
    reason="Calyx #1803 tree not available (set OC_FEATURED_GENUS_ROOT)",
)

if str(FG_ROOT) not in sys.path:
    sys.path.insert(0, str(FG_ROOT))


def _extend_app_path() -> None:
    """Make `app.featured_genus` resolvable when `app` already came from the
    Matrix chain tree (a regular package there). Extending __path__ is the
    standard pkgutil mechanism; the two trees contribute disjoint submodules
    (featured_genus / database / readiness / routers.orchid_widgets exist only
    in the #1803 tree), so no module identity is shadowed."""
    if not (FG_ROOT / "app" / "featured_genus" / "profile.py").is_file():
        return
    try:
        import app

        fg_app = str(FG_ROOT / "app")
        if fg_app not in list(app.__path__):
            app.__path__.append(fg_app)
        try:
            import app.routers as routers_pkg

            fg_routers = str(FG_ROOT / "app" / "routers")
            if fg_routers not in list(routers_pkg.__path__):
                routers_pkg.__path__.append(fg_routers)
        except ImportError:
            pass
    except ImportError:
        pass


_extend_app_path()

# --------------------------------------------------------------------------
# Python port of frontend #914 validation rules (verification oracle)
# --------------------------------------------------------------------------

EVIDENCE_STATES = ("known", "unknown", "unavailable")
MEDIA_STATUSES = ("ok", "no_approved_media", "service_error")

# src/lib/featuredTaxonContinuum.ts @ aa6117b9 (normalizeFeaturedTaxonGenus)
SAFE_FEATURED_GENUS_RE = re.compile(r"^[A-Z][A-Za-z-]+$")
MAX_FEATURED_GENUS_LENGTH = 120

# src/lib/featuredGenus.ts @ eb33fa63 (FEATURED_GENERA, verbatim order)
FRONTEND_FEATURED_GENERA = [
    "Cattleya",
    "Dracula",
    "Masdevallia",
    "Dendrobium",
    "Bulbophyllum",
    "Catasetum",
    "Vanilla",
    "Phalaenopsis",
]
FRONTEND_WINDOW_MS = 12 * 60 * 60 * 1000


def fe_normalize_genus(value):
    genus = str(value if value is not None else "").strip()
    if (
        not genus
        or len(genus) > MAX_FEATURED_GENUS_LENGTH
        or not SAFE_FEATURED_GENUS_RE.fullmatch(genus)
    ):
        raise ValueError("A bounded canonical featured-taxon genus is required")
    return genus


def _is_record(v):
    return isinstance(v, dict)


def _evidence_state(v):
    return v if isinstance(v, str) and v in EVIDENCE_STATES else None


def _non_negative_number(v):
    """frontend nonNegativeNumber: null stays null; undefined (missing) rejects."""
    if v is None:
        return None
    if isinstance(v, bool):
        return _REJECT
    if isinstance(v, (int, float)) and v >= 0:
        return v
    return _REJECT


def _optional_string(v):
    if v is None:
        return None
    return v if isinstance(v, str) else _REJECT


def _string_list(v):
    if not isinstance(v, list):
        return None
    if not all(isinstance(item, str) for item in v):
        return None
    return v


class _Reject:
    pass


_REJECT = _Reject()


def _normalize_domain_record(value):
    if not _is_record(value):
        return None
    # Both linkage counters must be present (null is explicit; missing rejects).
    if "linked_nodes" not in value or "linked_edges" not in value:
        return None
    state = _evidence_state(value.get("state"))
    nodes = _non_negative_number(value.get("linked_nodes"))
    edges = _non_negative_number(value.get("linked_edges"))
    if not state or nodes is _REJECT or edges is _REJECT:
        return None
    return {"state": state, "linked_nodes": nodes, "linked_edges": edges}


def fe_normalize_profile(payload):
    """Port of normalizeFeaturedGenusProfile; returns dict or None (fail closed)."""
    if not _is_record(payload):
        return None
    if payload.get("contract") != "featured-genus-profile/v1":
        return None
    if payload.get("status") != "ok":
        return None

    accepted = _optional_string(payload.get("accepted_genus"))
    requested = _optional_string(payload.get("requested_genus"))
    if not accepted or not requested:
        return None

    taxonomy = payload.get("taxonomy")
    media = payload.get("media")
    habitat = payload.get("habitat")
    graph = payload.get("knowledge_graph")
    if not all(map(_is_record, (taxonomy, media, habitat, graph))):
        return None

    tax_state = _evidence_state(taxonomy.get("state"))
    tax_count = _non_negative_number(taxonomy.get("recorded_species_count"))
    tax_names = _string_list(taxonomy.get("representative_names"))
    if not tax_state or tax_count is _REJECT or tax_names is None:
        return None

    media_state = _evidence_state(media.get("state"))
    media_status = media.get("status")
    returned = _non_negative_number(media.get("returned_count"))
    if not media_state or media_status not in MEDIA_STATUSES or returned is _REJECT:
        return None

    hab_state = _evidence_state(habitat.get("state"))
    hab_min = _non_negative_number(habitat.get("min_elevation_m"))
    hab_max = _non_negative_number(habitat.get("max_elevation_m"))
    hab_climate = _optional_string(habitat.get("climate_tag"))
    hab_collection = _optional_string(habitat.get("collection_tag"))
    hab_source = _optional_string(habitat.get("source"))
    if (
        not hab_state
        or hab_min is _REJECT
        or hab_max is _REJECT
        or hab_climate is _REJECT
        or hab_collection is _REJECT
        or hab_source is _REJECT
    ):
        return None

    g_state = _evidence_state(graph.get("state"))
    g_nodes = _non_negative_number(graph.get("node_count"))
    g_edges = _non_negative_number(graph.get("edge_count"))
    if not g_state or g_nodes is _REJECT or g_edges is _REJECT:
        return None

    domains = payload.get("domains")
    if not _is_record(domains):
        return None
    for raw in domains.values():
        if _normalize_domain_record(raw) is None:
            return None

    gaps = _string_list(payload.get("gaps"))
    if gaps is None:
        return None

    provenance = payload.get("provenance")
    if provenance is not None:
        if not _is_record(provenance):
            pass  # frontend: non-record provenance just yields {}
        else:
            provenance = {k: v for k, v in provenance.items() if isinstance(v, str)}

    return {
        "requested_genus": requested,
        "accepted_genus": accepted,
        "taxonomy_state": tax_state,
        "media_state": media_state,
        "habitat_state": hab_state,
        "graph_state": g_state,
        "gaps": gaps,
    }


def fe_normalize_selection(payload):
    """Port of normalizeFeaturedGenusSelection; returns dict or None."""
    if not _is_record(payload):
        return None
    if payload.get("contract") != "featured-genus-selection/v1":
        return None
    genus = _optional_string(payload.get("genus"))
    source = payload.get("source")
    if not genus or source not in ("editorial_override", "deterministic_rotation"):
        return None
    try:
        fe_normalize_genus(genus)
    except ValueError:
        return None
    window = payload.get("window")
    if not _is_record(window):
        return None
    window_seconds = _non_negative_number(window.get("window_seconds"))
    window_index = _non_negative_number(window.get("index"))
    seconds_remaining = _non_negative_number(window.get("seconds_remaining"))
    if (
        not window_seconds
        or window_seconds <= 0
        or window_index is _REJECT
        or window_index is None
        or seconds_remaining is _REJECT
        or seconds_remaining is None
    ):
        return None
    override = payload.get("override")
    override_status = (
        override.get("status")
        if _is_record(override) and isinstance(override.get("status"), str)
        else "unknown"
    )
    return {
        "genus": genus,
        "source": source,
        "window_seconds": window_seconds,
        "window_index": window_index,
        "seconds_remaining": seconds_remaining,
        "override_status": override_status,
    }


# --------------------------------------------------------------------------
# Backend fixtures (mirror the PR #1803 test fakes; no database is opened)
# --------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def first(self):
        return self._rows[0] if self._rows else None

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _FakeConnection:
    def __init__(self, *, exists=True, count=2, widget=None, media_rows=None, media_error=False):
        self.exists = exists
        self.count = count
        self.widget = widget
        self.media_rows = media_rows or []
        self.media_error = media_error

    def execute(self, sql, params):
        statement = str(sql)
        if "FROM public.orchid_images" in statement:
            if self.media_error:
                raise RuntimeError("media store down")
            return _FakeResult(self.media_rows)
        if "v_genus_of_day_cards" in statement:
            return _FakeResult([self.widget] if self.widget else [])
        if "COUNT(DISTINCT scientific_name)" in statement:
            return _FakeResult([{"recorded_names": self.count}])
        if "SELECT DISTINCT scientific_name" in statement:
            return _FakeResult(
                [
                    {"scientific_name": "Cattleya labiata Lindl."},
                    {"scientific_name": "Cattleya trianae Linden & Rchb.f."},
                ]
            )
        return _FakeResult([{"exists": 1}] if self.exists else [])

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class _FakeEngine:
    def __init__(self, conn):
        self._conn = conn

    def connect(self):
        return self._conn


def _image_row(image_id, scientific_name, url):
    return {
        "image_id": image_id,
        "taxonomy_id": 100,
        "scientific_name": scientific_name,
        "genus": "Cattleya",
        "image_url": url,
        "image_source": "GBIF",
        "image_license": "CC-BY",
        "image_rights_holder": "An Observer",
        "observer_name": "An Observer",
        "gbif_occurrence_key": "12345",
        "image_type": "photograph",
        "image_description": "",
        "alt_text": "",
        "is_duplicate": False,
    }


def _graph_payload():
    return {
        "focal_node": {"id": 1, "label": "Cattleya"},
        "graph": {"node_count": 40, "edge_count": 55},
        "pagination": {"truncated": False, "next_offset": None},
        "domain_coverage": {"literature": {"nodes": 3, "edges": 2}},
    }


@pytest.fixture()
def backend():
    from app.featured_genus import profile as profile_module
    from app.featured_genus import selection as selection_module

    return profile_module, selection_module


def _profile(profile_module, conn, graph=("ok", None)):
    profile_module.get_engine = lambda: _FakeEngine(conn)  # isolated tree module
    return profile_module.build_featured_genus_profile(
        "Cattleya", graph_loader=lambda genus: graph
    )


# --------------------------------------------------------------------------
# Contract compatibility tests
# --------------------------------------------------------------------------


@fg_missing
def test_full_profile_payload_accepted_by_frontend_rules(backend):
    profile_module, _ = backend
    conn = _FakeConnection(
        widget={
            "genus": "Cattleya",
            "climate_tag": "cool-intermediate",
            "collection_tag": "andean",
            "min_elevation": 800,
            "max_elevation": 2400,
            "accepted_scientific_name": "Cattleya trianae Linden & Rchb.f.",
            "image_count": 41,
        },
        media_rows=[
            _image_row(1, "Cattleya labiata Lindl.", "https://example.org/labiata.jpg"),
            _image_row(3, "Cattleya trianae Linden & Rchb.f.", "https://example.org/trianae.jpg"),
        ],
    )
    payload = _profile(profile_module, conn, graph=("ok", _graph_payload()))
    normalized = fe_normalize_profile(payload)
    assert normalized is not None, "frontend read model rejected a real backend payload"
    assert normalized["taxonomy_state"] == "known"
    assert normalized["media_state"] == "known"
    assert normalized["habitat_state"] == "known"
    assert normalized["graph_state"] == "known"


@fg_missing
def test_degraded_states_accepted_exactly_as_emitted(backend):
    profile_module, _ = backend
    # media service error + missing habitat card + graph unanswered
    payload = _profile(
        profile_module,
        _FakeConnection(widget=None, media_error=True),
        graph=("unavailable", None),
    )
    normalized = fe_normalize_profile(payload)
    assert normalized is not None
    assert normalized["media_state"] == "unavailable"
    assert normalized["habitat_state"] == "unknown"
    assert normalized["graph_state"] == "unavailable"
    assert payload["gaps"] == []  # unavailable graph yields no gap claims


@fg_missing
def test_no_approved_media_is_explicit_image_unavailable_state(backend):
    profile_module, _ = backend
    payload = _profile(
        profile_module, _FakeConnection(media_rows=[]), graph=("unknown", None)
    )
    assert payload["media"]["state"] == "unknown"
    assert payload["media"]["status"] == "no_approved_media"
    assert payload["media"]["items"] == []
    normalized = fe_normalize_profile(payload)
    assert normalized is not None
    assert normalized["media_state"] == "unknown"


@fg_missing
def test_invalid_genus_verdict_matches_frontend_shape(backend):
    profile_module, _ = backend
    payload = _profile(profile_module, _FakeConnection(exists=False))
    # Frontend fetchFeaturedGenusProfile: status 'invalid_genus' passes through
    # before normalization; the verdict must carry the contract id.
    assert payload["contract"] == "featured-genus-profile/v1"
    assert payload["status"] == "invalid_genus"
    assert payload["accepted_genus"] is None
    assert "taxonomy" not in payload
    # ...and it must NOT be mistaken for an ok payload by the normalizer.
    assert fe_normalize_profile(payload) is None


@fg_missing
def test_off_contract_payloads_rejected_by_frontend_rules(backend):
    profile_module, _ = backend
    good = _profile(profile_module, _FakeConnection(), graph=("ok", _graph_payload()))
    assert fe_normalize_profile(good) is not None

    wrong_contract = dict(good, contract="featured-genus-profile/v0")
    assert fe_normalize_profile(wrong_contract) is None

    bad_vocab = dict(good)
    bad_vocab["taxonomy"] = dict(good["taxonomy"], state="absent")
    assert fe_normalize_profile(bad_vocab) is None

    negative = dict(good)
    negative["taxonomy"] = dict(good["taxonomy"], recorded_species_count=-3)
    assert fe_normalize_profile(negative) is None

    malformed_domain = dict(good)
    malformed_domain["domains"] = dict(good["domains"])
    malformed_domain["domains"]["traits"] = {"state": "known"}  # missing counters
    assert fe_normalize_profile(malformed_domain) is None


@fg_missing
def test_selection_payload_accepted_and_rotation_matches_frontend(backend):
    _, selection_module = backend

    # Candidate lists identical (backend DEFAULT_ROTATION_CANDIDATES vs
    # frontend FEATURED_GENERA) — required for identity agreement.
    assert list(selection_module.DEFAULT_ROTATION_CANDIDATES) == FRONTEND_FEATURED_GENERA

    for epoch in (0, 43200 * 3 + 5, 43200 * 8, 1_700_000_000, 1_761_000_000):
        payload = selection_module.select_featured_genus(epoch, policy={})
        normalized = fe_normalize_selection(payload)
        assert normalized is not None, f"selection payload rejected at epoch {epoch}"
        # Window math equivalence: floor(ms/12h) % n == floor(s/43200) % n
        fe_index = ((epoch * 1000) // FRONTEND_WINDOW_MS) % len(FRONTEND_FEATURED_GENERA)
        assert payload["window"]["index"] == fe_index
        assert normalized["genus"] == FRONTEND_FEATURED_GENERA[fe_index]
        assert normalized["source"] == "deterministic_rotation"

    # Editorial override path is also on-contract for the frontend.
    override = {
        "genus": "Dracula",
        "reason": "Editorial feature.",
        "reviewer": "science-editor",
        "expires_at": "2999-01-01",
    }
    payload = selection_module.select_featured_genus(0, policy={"override": override})
    normalized = fe_normalize_selection(payload)
    assert normalized is not None
    assert normalized["genus"] == "Dracula"
    assert normalized["source"] == "editorial_override"
    assert normalized["override_status"] == "active"


@fg_missing
def test_genus_boundary_validators_agree(backend):
    _, selection_module = backend
    accept = ["Cattleya", "Paphiopedilum", "Dracula"]
    reject = ["Cattleya labiata", "cattleya", "", "Cattleya?x=1", "/atlas", "X", "C" * 121, None]
    for value in accept:
        assert selection_module.canonical_genus(value) == fe_normalize_genus(value)
    for value in reject:
        with pytest.raises(ValueError):
            selection_module.canonical_genus(value)
        with pytest.raises(ValueError):
            fe_normalize_genus(value)
