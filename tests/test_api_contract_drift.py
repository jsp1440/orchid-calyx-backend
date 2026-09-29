"""Tests for frontend/backend API contract drift detection.

The value of this detector is precision. A missed defect is a dead panel in
production; a false one is busywork queued into an autonomous engine, which is
worse, because it is self-inflicted and repeats.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api_contract_drift import (
    DEFAULT_MAX_WORK_ITEMS,
    PARAM_SENTINEL,
    TARGET_CALYX,
    TARGET_PUBLIC_API,
    ApiCallSite,
    ContractDriftWorkSource,
    build_report,
    build_route_matchers,
    detect_drift,
    find_relative_fetches,
    findings_to_work_items,
    load_routes,
    normalize_call_path,
    path_is_served,
    scan_frontend_calls,
    stable_identity,
    strip_comments,
)


def site(
    raw: str, *, target: str = TARGET_CALYX, relative: bool = False
) -> ApiCallSite:
    return ApiCallSite(
        raw_path=raw, file="src/x.ts", line=1, target=target, relative=relative
    )


# ---------------------------------------------------------------------------
# Path normalization and matching
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("/api/species", "/api/species"),
        ("/api/species/", "/api/species"),
        ("/api/species?limit=5", "/api/species"),
        ("/api/intake/${id}/approve", f"/api/intake/{PARAM_SENTINEL}/approve"),
        ("/api/projects/:slug", f"/api/projects/{PARAM_SENTINEL}"),
    ],
)
def test_normalization(raw: str, expected: str):
    assert normalize_call_path(raw) == expected


def test_a_templated_call_matches_a_parameterized_route():
    """The false-positive that mattered: this looked missing but is served."""
    matchers = build_route_matchers(["/api/intake/{source_id}/approve"])
    assert path_is_served(normalize_call_path("/api/intake/${id}/approve"), matchers)


def test_a_templated_call_matches_a_literal_route_segment():
    matchers = build_route_matchers(["/api/lexicon/search"])
    assert path_is_served(normalize_call_path("/api/lexicon/${which}"), matchers)


def test_a_path_converter_route_spans_separators():
    matchers = build_route_matchers(["/api/concepts/{id_or_uri:path}"])
    assert path_is_served("/api/concepts/http://example.org/a/b", matchers)


def test_an_unserved_path_is_not_matched():
    matchers = build_route_matchers(["/api/species", "/api/species/{id}"])
    assert not path_is_served("/api/zoo/status", matchers)


def test_a_route_prefix_does_not_match_a_longer_call():
    matchers = build_route_matchers(["/api/species"])
    assert not path_is_served("/api/species/extra/deep", matchers)


# ---------------------------------------------------------------------------
# Comment stripping: the busywork guard
# ---------------------------------------------------------------------------


def test_paths_named_in_comments_are_not_calls():
    text = """
    /** Producer contract: GET /api/mission-control/thing */
    // see also '/api/other/thing'
    const real = fetch(`${BASE}/api/real/thing`);
    """
    stripped = strip_comments(text)
    assert "/api/mission-control/thing" not in stripped
    assert "/api/other/thing" not in stripped
    assert "/api/real/thing" in stripped


def test_stripping_comments_preserves_line_numbers():
    text = "line1\n/* two\nthree */\nline4\n"
    assert strip_comments(text).count("\n") == text.count("\n")


def test_scanner_ignores_documentation_paths(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.ts").write_text(
        "/** calls /api/documented/only */\n"
        "const r = fetch(`${CALYX_BACKEND_BASE_URL}/api/real/call`);\n",
        encoding="utf-8",
    )
    found = {s.normalized for s in scan_frontend_calls(src)}
    assert "/api/real/call" in found
    assert "/api/documented/only" not in found


def test_scanner_skips_test_files(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.test.ts").write_text("fetch('/api/in/a/test');\n", encoding="utf-8")
    assert scan_frontend_calls(src) == []


# ---------------------------------------------------------------------------
# Relative origins: the silent-failure class
# ---------------------------------------------------------------------------


def test_a_relative_fetch_is_found(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "bad.ts").write_text(
        "await fetch('/api/crm/abc/subscribe', { method: 'POST' });\n", encoding="utf-8"
    )
    sites = find_relative_fetches(src)
    assert len(sites) == 1
    assert sites[0].relative is True


def test_an_absolute_fetch_is_not_flagged_relative(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "good.ts").write_text(
        "await fetch(`${CALYX_BACKEND_BASE_URL}/api/crm/abc/subscribe`);\n",
        encoding="utf-8",
    )
    assert find_relative_fetches(src) == []


def test_relative_origin_outranks_a_missing_producer():
    findings = detect_drift(
        [site("/api/absent/thing")],
        ["/api/present"],
        relative_sites=[site("/api/relative/thing", relative=True)],
    )
    assert findings[0].kind == "relative_origin"
    assert findings[0].severity == "high"
    assert findings[1].kind == "missing_producer"


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def test_a_served_call_produces_no_finding():
    assert detect_drift([site("/api/present")], ["/api/present"]) == []


def test_an_unserved_call_is_reported_once_with_every_site():
    calls = [
        ApiCallSite("/api/gone", "src/a.ts", 3, TARGET_CALYX, False),
        ApiCallSite("/api/gone", "src/b.ts", 9, TARGET_CALYX, False),
    ]
    findings = detect_drift(calls, ["/api/present"])
    assert len(findings) == 1
    assert len(findings[0].call_sites) == 2


def test_public_api_drift_is_reported_but_not_actionable_here():
    """Real, but this repository cannot serve it, so it must not become work."""
    findings = detect_drift(
        [site("/api/zoo/status", target=TARGET_PUBLIC_API)], ["/api/present"]
    )
    assert len(findings) == 1
    assert findings[0].actionable_here is False
    assert findings_to_work_items(findings) == []


def test_calyx_drift_is_actionable_here():
    findings = detect_drift([site("/api/calyx/thing")], ["/api/present"])
    assert findings[0].actionable_here is True
    assert len(findings_to_work_items(findings)) == 1


# ---------------------------------------------------------------------------
# Boundedness: an improvement loop must not flood the queue
# ---------------------------------------------------------------------------


def test_work_items_are_capped():
    findings = detect_drift(
        [site(f"/api/missing/{n}") for n in range(100)], ["/api/present"]
    )
    assert len(findings) == 100
    assert len(findings_to_work_items(findings)) == DEFAULT_MAX_WORK_ITEMS


def test_the_cap_is_configurable_and_respected():
    findings = detect_drift(
        [site(f"/api/missing/{n}") for n in range(20)], ["/api/present"]
    )
    assert len(findings_to_work_items(findings, limit=3)) == 3


def test_work_item_identity_is_stable_across_processes():
    """Python's salted hash would give the same defect a new id every run."""
    first = stable_identity("/api/crm/{*}/subscribe")
    assert first == stable_identity("/api/crm/{*}/subscribe")
    assert first != stable_identity("/api/other/path")
    assert 0 <= first < 9_000


def test_the_same_defect_yields_the_same_work_item():
    findings = detect_drift([site("/api/calyx/thing")], ["/api/present"])
    assert findings_to_work_items(findings) == findings_to_work_items(findings)


def test_the_work_source_reports_each_defect_once_then_starves():
    """Re-queueing the same snapshot every cycle is unbounded generation."""
    findings = detect_drift([site("/api/calyx/thing")], ["/api/present"])
    source = ContractDriftWorkSource(findings=findings)
    assert len(source.discover(1)) == 1
    assert source.discover(2) == []
    assert source.discover(3) == []


def test_high_severity_work_is_ranked_ahead_of_medium():
    findings = detect_drift(
        [site("/api/absent")],
        ["/api/present"],
        relative_sites=[site("/api/relative", relative=True)],
    )
    items = findings_to_work_items(findings)
    assert items[0]["priority"] < items[1]["priority"]


# ---------------------------------------------------------------------------
# Report and IO
# ---------------------------------------------------------------------------


def test_report_separates_actionable_from_total():
    findings = detect_drift(
        [site("/api/calyx/a"), site("/api/pub/b", target=TARGET_PUBLIC_API)],
        ["/api/present"],
    )
    report = build_report(findings)
    assert report["total_findings"] == 2
    assert report["actionable_here"] == 1


def test_load_routes_accepts_both_shapes(tmp_path: Path):
    plain = tmp_path / "a.json"
    plain.write_text('["/api/one", "/api/two"]', encoding="utf-8")
    paired = tmp_path / "b.json"
    paired.write_text(
        '[["/api/one", ["GET"]], ["/api/two", ["POST"]]]', encoding="utf-8"
    )
    assert load_routes(plain) == load_routes(paired) == ["/api/one", "/api/two"]


def test_detection_is_deterministic():
    calls = [site(f"/api/missing/{n}") for n in range(10)]
    first = [f.path for f in detect_drift(calls, ["/api/present"])]
    second = [f.path for f in detect_drift(calls, ["/api/present"])]
    assert first == second


# ---------------------------------------------------------------------------
# Precision: never report a path that could not be read
# ---------------------------------------------------------------------------


def test_a_base_prefix_helper_is_not_a_call():
    """`/api/thing${path}` is a base a helper appends to, not an endpoint."""
    from runtime.api_contract_drift import UNPARSED

    assert normalize_call_path("/api/literature-extraction${path}") == UNPARSED


def test_a_truncated_template_hole_is_not_guessed_at():
    """An unreadable path is excluded, never reported as a guessed one."""
    from runtime.api_contract_drift import UNPARSED

    assert normalize_call_path("/api/species/${encodeURIComponent") == UNPARSED


def test_unreadable_paths_never_become_findings():
    from runtime.api_contract_drift import UNPARSED

    unreadable = ApiCallSite(
        raw_path="/api/thing${rest}",
        file="src/helper.ts",
        line=1,
        target=TARGET_CALYX,
        relative=False,
    )
    assert unreadable.normalized == UNPARSED
    assert detect_drift([unreadable], ["/api/present"]) == []


def test_an_interpolated_origin_prefix_is_still_scanned(tmp_path: Path):
    """`${BASE}/api/x` is the dominant call shape here and must be seen."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.ts").write_text(
        "fetch(`${CALYX_BACKEND_BASE_URL}/api/real/endpoint`);\n", encoding="utf-8"
    )
    assert {s.normalized for s in scan_frontend_calls(src)} == {"/api/real/endpoint"}


def test_a_call_with_a_function_in_its_template_hole_is_read_fully():
    assert (
        normalize_call_path("/api/species/${encodeURIComponent(name)}/dossier")
        == f"/api/species/{PARAM_SENTINEL}/dossier"
    )


def test_report_counts_excluded_call_sites():
    report = build_report([], unparsed=3)
    assert report["unparsed_call_sites"] == 3
