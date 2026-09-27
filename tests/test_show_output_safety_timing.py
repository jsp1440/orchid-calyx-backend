"""Output-safety helpers run in linear time on adversarial input.

``app.show_output_safety`` scans owner-supplied text (integration ``config_json``,
event text, message templates). A super-linear pattern there turns one stored value
into a slow create and a slow list for every later request, so each helper is timed
on inputs shaped to hit the worst case of every rule. Two assertions per case keep CI
stable while still meaningful:

* an absolute bound, generous against the measured cost (a 64 KiB config redacts in
  under 0.1 s on the reference sandbox; the bound is 1 s);
* near-linear scaling: 4x the input takes under 8x the time (with a 5 ms floor, so
  timer noise on tiny inputs cannot fail it).

The regression this pins: an all-uppercase 16K-character key took 2.2 s (64K: 37 s)
because the camelCase split was quadratic. All values are synthetic.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable

import pytest

from app import show_output_safety as safety

SMALL = 16 * 1024
LARGE = 64 * 1024  # MAX_CONFIG_JSON_CHARS
BOUND_SECONDS = 1.0
FLOOR_SECONDS = 0.005


def _best_of(fn: Callable[[], object], runs: int = 3) -> float:
    best = float("inf")
    for _ in range(runs):
        safety._is_secret_key_name.cache_clear()  # time the uncached cost
        start = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - start)
    return best


def _fill(item: str, size: int) -> str:
    """A JSON list of ``item`` repeated to just under ``size`` characters."""
    encoded = json.dumps(item)
    count = max(1, (size - 2) // (len(encoded) + 2))
    return json.dumps([item] * count)


def _key(size: int) -> str:
    return json.dumps({"A" * (size - 10): 1})


# Each builder returns a config_json of about ``size`` characters (never above
# MAX_CONFIG_JSON_CHARS) aimed at one rule's worst case.
CONFIG_BUILDERS: dict[str, Callable[[int], str]] = {
    "uppercase-dict-key": _key,
    "uppercase-pair-first-element": lambda n: json.dumps({"h": ["A" * (n - 20), "x"]}),
    "uppercase-name-field": lambda n: json.dumps(
        {"f": {"name": "A" * (n - 40), "value": "x"}}
    ),
    "mixed-case-key": lambda n: json.dumps({"aB" * ((n - 10) // 2): 1}),
    "name-then-spaces": lambda n: json.dumps({"v": "a" * 40 + " " * (n - 60)}),
    "name-then-spaces-scanned": lambda n: _fill("a" * 40 + " " * 4000, n),
    "words": lambda n: _fill("a " * 2040, n),
    "secret-words": lambda n: _fill("password x " * 370, n),
    "cli-flags": lambda n: _fill("-a " * 1360, n),
    "unterminated-double-quotes": lambda n: _fill('a:"' * 1300, n),
    "unterminated-single-quote": lambda n: _fill("a:'" + "x" * 4000, n),
    "escaped-quotes": lambda n: _fill('x="\\' * 1000, n),
    "unterminated-braces": lambda n: _fill("a:{" * 1360, n),
    "query-braces": lambda n: _fill("?a={" * 1020, n),
    "url-schemes": lambda n: _fill("a://a:" * 680, n),
    "url-many-at": lambda n: _fill("a://a:" + "@" * 4000, n),
    "auth-schemes": lambda n: _fill("Bearer " * 580, n),
    "token-run": lambda n: _fill("ab1" * 1360, n),
    "uppercase-run": lambda n: _fill("A" * 4080, n),
    "long-free-text": lambda n: json.dumps({"v": "a:" * ((n - 20) // 2)}),
    "many-keys": lambda n: json.dumps({f"k{i}": "v" for i in range(n // 14)}),
    "many-near-cap-keys": lambda n: json.dumps(
        {"A" * 250 + str(i): 1 for i in range(n // 262)}
    ),
    "embedded-json-layers": lambda n: json.dumps(
        {"a": json.dumps({"b": json.dumps({"c": "x" * (n // 2)})})}
    ),
    "deep-nesting": lambda n: "[" * (n // 2 - 1) + "]" * (n // 2 - 1),
    # header lines, curl -H / -u and HTTP Digest parameters
    "header-line-names": lambda n: _fill(("A" * 63 + " " * 8 + "x\n") * 56, n),
    "header-line-values": lambda n: _fill("token:" + " a" * 2040, n),
    "cli-header-single": lambda n: _fill("-H 'a:" * 680, n),
    "cli-header-double-escapes": lambda n: _fill('-H "a:\\' * 580, n),
    "cli-user-flags": lambda n: _fill("-u " * 1360, n),
    "cli-user-quotes": lambda n: _fill('-u "' * 1020, n),
    "cli-user-clusters": lambda n: _fill("-abcdefu" * 510, n),
    "digest-schemes": lambda n: _fill("Digest a=" * 450, n),
    "digest-params": lambda n: _fill("Digest a=" + 'response="' * 400, n),
    "flat-header-list": lambda n: json.dumps(["X-Api-Key", "v"] * (n // 20)),
}


@pytest.mark.parametrize("case", CONFIG_BUILDERS)
def test_config_redaction_is_bounded_and_linear(case):
    build = CONFIG_BUILDERS[case]
    small, large = build(SMALL), build(LARGE)
    assert len(large) <= safety.MAX_CONFIG_JSON_CHARS
    t_small = _best_of(lambda: safety.redact_config_json(small))
    t_large = _best_of(lambda: safety.redact_config_json(large))
    assert t_large < BOUND_SECONDS, f"{case}: {t_large:.3f}s for {len(large)} chars"
    assert t_large < 8 * max(t_small, FLOOR_SECONDS), (
        f"{case}: {t_small:.4f}s -> {t_large:.4f}s for 4x input"
    )


TEXT_BUILDERS: dict[str, Callable[[int], str]] = {
    "line-breaks": lambda n: "a\u2028b\r\n;,\\\x85" * (n // 10),
    "multibyte": lambda n: "é" * n,
    "controls": lambda n: "\x01\x9f" * (n // 2),
}


@pytest.mark.parametrize("case", TEXT_BUILDERS)
def test_ics_text_line_is_bounded_and_linear(case):
    build = TEXT_BUILDERS[case]
    small, large = build(SMALL), build(LARGE)
    t_small = _best_of(lambda: safety.ics_text_line("DESCRIPTION", small))
    t_large = _best_of(lambda: safety.ics_text_line("DESCRIPTION", large))
    assert t_large < BOUND_SECONDS
    assert t_large < 8 * max(t_small, FLOOR_SECONDS)


def test_json_nesting_depth_is_linear():
    small = '["\\"[", {' * (SMALL // 8)
    large = '["\\"[", {' * (LARGE // 8)
    t_small = _best_of(lambda: safety.json_nesting_depth(small))
    t_large = _best_of(lambda: safety.json_nesting_depth(large))
    assert t_large < BOUND_SECONDS
    assert t_large < 8 * max(t_small, FLOOR_SECONDS)


def test_template_render_is_bounded_and_linear():
    context = {"v": "x"}
    small = "{v}{{}}{" * (safety.MAX_TEMPLATE_CHARS // 32)
    large = "{v}{{}}{" * (safety.MAX_TEMPLATE_CHARS // 8)
    t_small = _best_of(lambda: safety.render_template_text(small, context, field="b"))
    t_large = _best_of(lambda: safety.render_template_text(large, context, field="b"))
    assert t_large < BOUND_SECONDS
    assert t_large < 8 * max(t_small, FLOOR_SECONDS)


# The patterns added for Digest parameters, curl ``-u``/``-H`` and header lines, run
# directly on 64 KiB (past MAX_SCAN_CHARS, which only protects them in production)
# pathological strings: each must stay linear on its own.
PATTERN_SIZE = 64 * 1024
PATTERN_BOUND_SECONDS = 0.25
PATTERN_INPUTS: dict[str, tuple[object, str]] = {
    "header-line-names": (safety._HEADER_LINE, "A" * 63 + " " * 8 + "x\n"),
    "header-line-values": (safety._HEADER_LINE, "token:" + " a" * 2000 + "\n"),
    "cli-header-single": (safety._CLI_HEADERS[1], "-H 'a:"),
    "cli-header-double": (safety._CLI_HEADERS[0], '-H "a:\\'),
    "cli-header-names": (safety._CLI_HEADERS[0], '-H "' + "a" * 63 + " "),
    "cli-user-flags": (safety._CLI_USER, "-u "),
    "cli-user-quotes": (safety._CLI_USER, '-u "'),
    "cli-user-clusters": (safety._CLI_USER, "-abcdefu"),
    "cli-user-long": (safety._CLI_USER, "--user"),
    "digest-scheme": (safety._DIGEST_SCHEME, "digest " + "a" * 40 + " "),
    "digest-params": (safety._DIGEST_SECRET_PARAM, 'response="'),
    "digest-escapes": (safety._DIGEST_SECRET_PARAM, 'cnonce="\\'),
}


@pytest.mark.parametrize("case", PATTERN_INPUTS)
def test_new_patterns_are_linear_on_64k_pathological_input(case):
    pattern, unit = PATTERN_INPUTS[case]
    small = (unit * (SMALL // len(unit) + 1))[:SMALL]
    large = (unit * (PATTERN_SIZE // len(unit) + 1))[:PATTERN_SIZE]
    assert len(large) == PATTERN_SIZE  # 65,536 characters
    t_small = _best_of(lambda: pattern.sub("", small))
    t_large = _best_of(lambda: pattern.sub("", large))
    assert t_large < PATTERN_BOUND_SECONDS, f"{case}: {t_large:.3f}s"
    assert t_large < 8 * max(t_small, FLOOR_SECONDS)


def test_digest_mask_and_list_redaction_are_linear_on_64k_input():
    digest = "Digest a=" + 'response="x", cnonce=y, ' * (PATTERN_SIZE // 24)
    headers = ["Accept", "a", "X-Api-Key", "k"] * (PATTERN_SIZE // 32)
    assert len(digest) > 65_000 and len(json.dumps(headers)) > 65_000
    assert _best_of(lambda: safety._mask_digest_params(digest)) < PATTERN_BOUND_SECONDS
    assert _best_of(lambda: safety._redact_list(headers, 0)) < BOUND_SECONDS
