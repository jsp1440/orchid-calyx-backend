"""Owner-view ``config_json`` redaction: remaining gaps (Release 1 ledger).

``app.show_output_safety.redact_config_json`` masks secrets in the owner-only
show-integration responses. These cases close the gaps left after the Digest,
``curl -u`` and header-list rounds:

* one ``-u`` value with an unterminated quote swallowed the opening quote of a later
  ``-u`` password, so the later password's tail was printed; a value that crosses a
  line break, reaches an unterminated quote or contains another credential flag now
  masks to the end of the text;
* an unquoted ``\\`` line continuation inside a ``-u`` password;
* HTTPie ``-a user:pw`` / ``--auth user:pw`` / ``--auth=user:pw``;
* odd-length flat header lists, and flat lists whose values are nested lists/objects;
* Digest ``response``/``cnonce`` stored as dict keys beside a ``"Digest"`` value;
* ``password =`` followed by more than 8 whitespace characters, and doubled
  separators (``password ==``, ``password = =``).

Every result must stay valid JSON, redaction must be idempotent, and every new pattern
is linear (64 KiB and 256 KiB hostile inputs). Every value is synthetic.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable

import pytest

from app import show_output_safety as safety
from app.show_output_safety import REDACTED, redact_config_json

SECRET = "Zq9sEcr"  # appears in no expected output


def _redact(value: object) -> object:
    return json.loads(redact_config_json(json.dumps(value)))


def _assert_masked_and_idempotent(value: object, expected: object) -> None:
    out = redact_config_json(json.dumps(value))
    parsed = json.loads(out)  # valid JSON
    assert parsed == expected
    assert SECRET not in out and "sEcr" not in out
    assert redact_config_json(out) == out  # idempotent


# --- curl -u: unterminated quotes, line breaks, continuations ------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        # the first value's quote closes on the later value's opening quote
        (f'curl -u a:"x\ncurl -u b:"{SECRET} two" -s', "curl -u a:***"),
        (f"curl -u a:'x -s; curl -u b:'{SECRET} two' -s", "curl -u a:***"),
        (f"curl -u 'a:x -s -u b:'{SECRET} two'", "curl -u 'a:***"),
        # an unterminated quote runs to the end
        (f"curl -u admin:'{SECRET} -s", "curl -u admin:***"),
        (f'curl -u admin:"{SECRET}\\" -s', "curl -u admin:***"),
        # a username that crosses a line is dropped too
        (f'curl -u "alice -s\n-u bob:{SECRET} two"', "curl -u ***"),
        # unquoted backslash line continuation inside the password or the username
        (
            f"curl -u user:pa\\\nss-{SECRET} https://x.example.invalid",
            "curl -u user:***",
        ),
        (
            f"curl -u user:pass\\\n  {SECRET} https://x.example.invalid",
            "curl -u user:***",
        ),
        (f"curl -u us\\\ner:{SECRET} https://x.example.invalid", "curl -u ***"),
        # a backslash-escaped space keeps the word going
        (f"curl -u user:pa\\ ss{SECRET} -s", "curl -u user:*** -s"),
    ],
)
def test_cli_user_values_that_cannot_be_bounded_mask_to_the_end(value, expected):
    _assert_masked_and_idempotent({"note": value}, {"note": expected})


# --- HTTPie ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (
            f"http -a alice:{SECRET} https://api.example.invalid/v1",
            "http -a alice:*** https://api.example.invalid/v1",
        ),
        (
            f"http -a 'alice:{SECRET} two' https://api.example.invalid",
            "http -a 'alice:***' https://api.example.invalid",
        ),
        # --auth was already masked whole; it stays masked whole
        (f"http --auth alice:{SECRET} GET x", "http --auth *** GET x"),
        (f"http --auth=alice:{SECRET} GET x", "http --auth=*** GET x"),
        (f"http --auth 'alice:{SECRET} two' GET x", "http --auth *** GET x"),
    ],
)
def test_httpie_auth_passwords_are_masked(value, expected):
    _assert_masked_and_idempotent({"note": value}, {"note": expected})


@pytest.mark.parametrize(
    "value",
    [
        "http -a alice https://api.example.invalid",
        "ls -a /tmp",
        "tar -a -cf out.tar.gz dir",
    ],
)
def test_cli_flags_without_a_password_stay_readable(value):
    assert _redact({"note": value}) == {"note": value}


# --- flat header lists: odd length, nested values -------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (
            ["Accept", "a", "X-Api-Key", SECRET, "Via"],
            ["Accept", "a", "X-Api-Key", REDACTED, "Via"],
        ),
        (
            ["Accept", "a", "X-Api-Key", [SECRET]],
            ["Accept", "a", "X-Api-Key", REDACTED],
        ),
        (
            ["Accept", "a", "X-Api-Key", {"v": SECRET}],
            ["Accept", "a", "X-Api-Key", REDACTED],
        ),
        (
            ["Accept", ["a"], "X-Api-Key", SECRET],
            ["Accept", ["a"], "X-Api-Key", REDACTED],
        ),
        (["X-Api-Key", {"v": SECRET}], ["X-Api-Key", REDACTED]),
        (["X-Api-Key", [SECRET], "a"], ["X-Api-Key", REDACTED, REDACTED]),
        (
            ["Authorization", "Bearer", {"x": SECRET}],
            ["Authorization", REDACTED, REDACTED],
        ),
        (
            ["Accept", "a", "Via", "p", "Cookie", {"c": SECRET}, "Server"],
            ["Accept", "a", "Via", "p", "Cookie", REDACTED, "Server"],
        ),
    ],
)
def test_flat_header_lists_of_any_shape_mask_secret_values(value, expected):
    _assert_masked_and_idempotent({"headers": value}, {"headers": expected})


@pytest.mark.parametrize(
    "value",
    [
        ["Accept", "application/json", "Via"],
        ["Accept", {"q": 1}, "Via", ["proxy"]],
        ["region", "zone", "alpha"],
    ],
)
def test_flat_lists_without_secret_names_stay_readable(value):
    assert _redact({"headers": value}) == {"headers": value}


# --- Digest parameters as dict keys ------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (
            {"scheme": "Digest", "response": SECRET, "cnonce": SECRET, "nonce": "n1"},
            {
                "scheme": "Digest",
                "response": REDACTED,
                "cnonce": REDACTED,
                "nonce": "n1",
            },
        ),
        (
            {"type": "digest", "Response": SECRET, "realm": "r"},
            {"type": "digest", "Response": REDACTED, "realm": "r"},
        ),
        (
            {"kind": "http_digest", "CNonce": {"v": SECRET}},
            {"kind": "http_digest", "CNonce": REDACTED},
        ),
    ],
)
def test_digest_fields_beside_a_digest_scheme_are_masked(value, expected):
    _assert_masked_and_idempotent({"http": value}, {"http": expected})


def test_response_keys_without_a_digest_sibling_stay_readable():
    value = {"format": "json", "response": "ok", "cnonce_label": "c"}
    assert _redact({"http": value}) == {"http": value}
    assert _redact({"response": "ok"}) == {"response": "ok"}


# --- password = with long gaps and doubled separators ---------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (f"password ={' ' * 9}{SECRET}", f"password ={' ' * 9}***"),
        (f"password ={' ' * 40}{SECRET}", f"password ={' ' * 40}***"),
        (f"password{' ' * 20}{SECRET}", f"password{' ' * 20}***"),
        (f"password={' ' * 12}{SECRET}", f"password={' ' * 12}***"),
        (f'"password":{" " * 12}"{SECRET}"', f'"password":{" " * 12}***'),
        (f"token =\n\n\n\n\n\n\n\n\n\n{SECRET}", "token =\n\n\n\n\n\n\n\n\n\n***"),
        (f"password == {SECRET}", "password == ***"),
        (f"password = = {SECRET}", "password = = ***"),
        (f"password ==={SECRET}", "password ***"),
        (f"api_key : : {SECRET}", "api_key : ***"),
    ],
)
def test_secret_names_with_long_gaps_or_doubled_separators_are_masked(value, expected):
    _assert_masked_and_idempotent({"note": value}, {"note": expected})


@pytest.mark.parametrize(
    "value",
    [
        f"user ={' ' * 12}alice",
        f"region={' ' * 12}eu-west",
        "a == b",
        "timeout = = 30",
    ],
)
def test_non_secret_names_with_long_gaps_stay_readable(value):
    assert _redact({"note": value}) == {"note": value}


def test_mixed_config_is_valid_json_and_idempotent():
    config = {
        "cmd": f'curl -u a:"x\ncurl -u b:"{SECRET} two" -s',
        "httpie": f"http -a bob:{SECRET} https://x.example.invalid",
        "raw": ["Accept", "a", "X-Api-Key", {"v": SECRET}, "Via"],
        "digest": {"scheme": "Digest", "response": SECRET, "cnonce": SECRET},
        "note": f"password = = {SECRET}",
        "embedded": json.dumps({"headers": ["Cookie", [SECRET], "Via"]}),
    }
    out = redact_config_json(json.dumps(config))
    json.loads(out)
    assert SECRET not in out
    assert redact_config_json(out) == out


# --- linear time on 64 KiB and 256 KiB hostile inputs ---------------------------------------

SIZES = (64 * 1024, 256 * 1024)
BOUND_SECONDS = {64 * 1024: 1.0, 256 * 1024: 4.0}
FLOOR_SECONDS = 0.05  # timer noise under parallel CI load


def _best_of(fn: Callable[[], object], runs: int = 3) -> float:
    best = float("inf")
    for _ in range(runs):
        safety._is_secret_key_name.cache_clear()  # time the uncached cost
        started = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - started)
    return best


def _fill(unit: str, size: int) -> str:
    return (unit * (size // len(unit) + 1))[:size]


TEXT_INPUTS: dict[str, Callable[[int], str]] = {
    "cli-backslashes": lambda n: "-u a:" + "\\" * (n - 5),
    "cli-backslash-newlines": lambda n: _fill("-u a:" + "\\\n" * 100, n),
    "cli-escaped-spaces": lambda n: "-u a:" + _fill("\\ ", n - 5),
    "cli-unsure-quotes": lambda n: _fill("-u a:'x -u b:'", n),
    "cli-unsure-lines": lambda n: _fill('-u a:"x\n', n),
    "cli-unterminated": lambda n: _fill("-u a:" + "'b'c" * 50 + " ", n),
    "httpie-a": lambda n: _fill("-a ", n),
    "httpie-a-values": lambda n: _fill("-a a:b ", n),
    "httpie-auth": lambda n: _fill("--auth ", n),
    "many-names-then-gap": lambda n: "a " * 20 + "=" + " " * (n - 41),
    "long-gap-repeated": lambda n: _fill("password=" + " " * 9, n),
    "long-gap-to-end": lambda n: "password=" + " " * (n - 9),
    "doubled-separators": lambda n: _fill("a = = =", n),
    "separator-words": lambda n: "password " + _fill("= ", n - 9),
    "spaced-name-gap": lambda n: "password" + " " * (n - 8),
    "name-then-long-gaps": lambda n: _fill("a" * 40 + " " * 400, n),
}
TEXT_FUNCTIONS: dict[str, Callable[[str], object]] = {
    "cli_users": safety._mask_cli_users,
    "name_value_pairs": lambda t: safety._NAME_VALUE_PAIR.sub(
        safety._mask_if_secret_name, t
    ),
    "after_separators": safety._mask_after_separators,
    "spaced_values": safety._mask_spaced_values,
}


@pytest.mark.parametrize("size", SIZES)
@pytest.mark.parametrize("function", sorted(TEXT_FUNCTIONS))
@pytest.mark.parametrize("case", sorted(TEXT_INPUTS))
def test_new_text_rules_are_linear_on_hostile_input(case, function, size):
    fn = TEXT_FUNCTIONS[function]
    small, large = TEXT_INPUTS[case](size // 4), TEXT_INPUTS[case](size)
    assert len(large) == size
    t_small = _best_of(lambda: fn(small))
    t_large = _best_of(lambda: fn(large))
    assert t_large < BOUND_SECONDS[size], f"{case}/{function}: {t_large:.3f}s"
    assert t_large < 8 * max(t_small, FLOOR_SECONDS), (
        f"{case}/{function}: {t_small:.4f}s -> {t_large:.4f}s for 4x input"
    )


PATTERN_INPUTS: dict[str, tuple[object, str]] = {
    "cli-user-backslash": (safety._CLI_USER, "-u a:\\"),
    "cli-user-backslash-space": (safety._CLI_USER, "-u a\\ "),
    "cli-user-httpie": (safety._CLI_USER, "-a "),
    "cli-user-auth": (safety._CLI_USER, "--auth "),
    "cli-segment": (safety._CLI_SEGMENT, "a\\'\"\\"),
    "name-before-separator": (safety._NAME_BEFORE_SEPARATOR, "a= "),
    "name-before-separator-names": (safety._NAME_BEFORE_SEPARATOR, "a" * 41 + "="),
    "pair-value": (safety._PAIR_VALUE, 'a="\\'),
    "separator-run": (safety._SPACED_SEPARATOR, "=:"),
    "httpie-auth-type": (safety._HTTPIE_AUTH_TYPE, "-aaaaaa"),
    "name-value-doubled": (safety._NAME_VALUE_PAIR, "a = = = = "),
    "spaced-name": (safety._SPACED_NAME, "a "),
}


@pytest.mark.parametrize("size", SIZES)
@pytest.mark.parametrize("case", sorted(PATTERN_INPUTS))
def test_new_patterns_are_linear_on_hostile_input(case, size):
    pattern, unit = PATTERN_INPUTS[case]
    small, large = _fill(unit, size // 4), _fill(unit, size)
    t_small = _best_of(lambda: pattern.sub("", small))
    t_large = _best_of(lambda: pattern.sub("", large))
    assert t_large < BOUND_SECONDS[size], f"{case}: {t_large:.3f}s"
    assert t_large < 8 * max(t_small, FLOOR_SECONDS)


@pytest.mark.parametrize("size", SIZES)
def test_list_and_dict_redaction_are_linear_on_hostile_input(size):
    odd = ["Accept", "a", "X-Api-Key", {"v": "k"}] * (size // 40) + ["Via"]
    nested = ["X-Api-Key", ["k"], "Accept", {"q": 1}] * (size // 40)
    digest = {f"k{i}": "digest" for i in range(size // 20)}
    digest.update({"response": "r", "cnonce": "c"})
    for build in (
        lambda: safety._redact_list(odd, 0),
        lambda: safety._redact_list(nested, 0),
        lambda: safety._redact_dict(digest, 0),
    ):
        assert _best_of(build) < BOUND_SECONDS[size]


def test_config_redaction_of_new_shapes_is_bounded_at_the_64k_cap():
    for config in (
        json.dumps({"n": _fill('-u a:"x\n', 4000)}),
        json.dumps(["Accept", "a", "X-Api-Key", ["k"], "Via"] * 1300),
        json.dumps({f"k{i}": "Digest" for i in range(3000)}),
        json.dumps([_fill("password =" + " " * 20, 4000)] * 15),
    ):
        assert len(config) <= safety.MAX_CONFIG_JSON_CHARS
        elapsed = _best_of(lambda text=config: redact_config_json(text))
        assert elapsed < BOUND_SECONDS[64 * 1024]


# --- checker repair round 1 (#1709) ------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (f"http -aadmin:{SECRET} x", "http -aadmin:*** x"),
        (f"http -va admin:{SECRET} x", "http -va admin:*** x"),
        (f"http -ja 'admin:{SECRET} two' x", "http -ja 'admin:***' x"),
        (f"http -a=admin:{SECRET} x", "http -a=admin:*** x"),
    ],
)
def test_httpie_attached_and_combined_values_are_masked(value, expected):
    _assert_masked_and_idempotent({"note": value}, {"note": expected})


@pytest.mark.parametrize(
    "value",
    [
        f"http --auth-type=jwt -a {SECRET} GET x",
        f"http -A jwt -a{SECRET} GET x",
        f"http -A jwt -va {SECRET} GET x",
        f"http -A bearer -a {SECRET} GET x",
    ],
)
def test_httpie_token_without_a_colon_is_masked_after_an_auth_type(value):
    # other rules may mask the auth type too (over-redaction); the token never shows
    out = redact_config_json(json.dumps({"note": value}))
    assert SECRET not in out
    assert json.loads(out)["note"].endswith(" GET x")
    assert redact_config_json(out) == out


def test_httpie_a_over_masking_on_other_commands_is_fail_safe():
    # ``rsync -a host:path`` is masked like a credential (documented, fail safe);
    # an ``-a`` value with no colon and no auth type stays readable.
    assert _redact({"n": "rsync -a host:path /x"}) == {"n": "rsync -a host:*** /x"}
    assert _redact({"n": "ls -la /tmp"}) == {"n": "ls -la /tmp"}


@pytest.mark.parametrize(
    "value",
    [
        {"auth": "HTTPDigestAuth", "response": SECRET},
        {"cls": "digestauth", "response": SECRET},
        {"schemes": ["Digest"], "response": SECRET},
        {"meta": {"type": "Digest"}, "response": SECRET},
        {"digest": True, "response": SECRET, "cnonce": SECRET},
        {"scheme": "Digest", "params": {"response": SECRET}},
        {"scheme": "Dіgest", "CNONCE": SECRET},  # Cyrillic i
        {"x": json.dumps({"scheme": "digest"}), "response": SECRET},
    ],
)
def test_digest_mentions_anywhere_mask_response_and_cnonce(value):
    out = redact_config_json(json.dumps({"http": value}))
    assert SECRET not in out
    json.loads(out)
    assert redact_config_json(out) == out


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (
            ["Accept", "a", "x:y", "b", "X-Api-Key", SECRET],
            ["Accept", "a", "x:y", "b", "X-Api-Key", REDACTED],
        ),
        ([None, "a", "X-Api-Key", SECRET], [None, "a", "X-Api-Key", REDACTED]),
        (
            [1, "a", "X-Api-Key", SECRET, "Via"],
            [1, "a", "X-Api-Key", REDACTED, "Via"],
        ),
        (["X-Api-Key:", SECRET], ["X-Api-Key:", REDACTED]),
        (
            ["x", "X-Api-Key", SECRET, "Accept", "a"],
            ["x", "X-Api-Key", REDACTED, "Accept", "a"],
        ),
    ],
)
def test_ambiguous_flat_lists_mask_after_every_secret_name(value, expected):
    _assert_masked_and_idempotent({"headers": value}, {"headers": expected})


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (f"password = = = = = {SECRET}", "password = = = = = ***"),
        (f"password {'= ' * 12}{SECRET}", f"password {'= ' * 12}***"),
        (
            f"password ={' ' * 10}={' ' * 10}{SECRET}",
            f"password ={' ' * 10}={' ' * 10}***",
        ),
        (f"password={'=' * 20}{SECRET}", f"password={'=' * 20}***"),
        (
            f"password:{' ' * 12}={' ' * 12}{SECRET}",
            "password: ***",  # a header-shaped line masks its whole value
        ),
        # past the separator bound the rest of the text is masked
        (f"password {'= ' * 70}{SECRET} tail", "password ***"),
    ],
)
def test_many_separators_and_gaps_between_them_are_masked(value, expected):
    _assert_masked_and_idempotent({"note": value}, {"note": expected})


@pytest.mark.parametrize(
    "value",
    [
        "https://x.example.invalid/?token=***&page=2",
        "user=alice; region=eu",
        "timeout = = 30",
    ],
)
def test_separator_walk_keeps_ordinary_text(value):
    assert _redact({"note": value}) == {"note": value}


ROUND1_TEXT_INPUTS: dict[str, Callable[[int], str]] = {
    "httpie-attached": lambda n: _fill("-aa:b ", n),
    "httpie-clusters": lambda n: _fill("-vvvvva ", n),
    "httpie-auth-type-tokens": lambda n: "-A jwt " + _fill("-a t ", n - 7),
    "separator-words-bound": lambda n: "password " + _fill("= ", n - 9),
    "separator-gaps": lambda n: "password =" + _fill(" " * 10 + "=", n - 10),
    "separator-run": lambda n: "password" + "=" * (n - 8),
    "many-secret-names": lambda n: _fill("password= ", n),
}


@pytest.mark.parametrize("size", SIZES)
@pytest.mark.parametrize("function", sorted(TEXT_FUNCTIONS))
@pytest.mark.parametrize("case", sorted(ROUND1_TEXT_INPUTS))
def test_round1_text_rules_are_linear_on_hostile_input(case, function, size):
    fn = TEXT_FUNCTIONS[function]
    small, large = ROUND1_TEXT_INPUTS[case](size // 4), ROUND1_TEXT_INPUTS[case](size)
    t_small = _best_of(lambda: fn(small))
    t_large = _best_of(lambda: fn(large))
    assert t_large < BOUND_SECONDS[size], f"{case}/{function}: {t_large:.3f}s"
    assert t_large < 8 * max(t_small, FLOOR_SECONDS)


@pytest.mark.parametrize("size", SIZES)
def test_round1_list_and_digest_scans_are_linear(size):
    ambiguous = [None, "a", "X-Api-Key", "k", 1] * (size // 30)
    digest = {f"k{i}": {"v": ["x"]} for i in range(size // 20)}
    digest["z"] = "HTTPDigestAuth"
    for build in (
        lambda: safety._redact_list(ambiguous, 0),
        lambda: safety._mentions_digest(digest),
        lambda: safety._redact_dict(digest, 0),
    ):
        assert _best_of(build) < BOUND_SECONDS[size]
