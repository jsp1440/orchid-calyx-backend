"""Integration ``config_json`` redaction: broader secret keys and secret-shaped values.

``app.show_output_safety.redact_config_json`` masks secrets in owner responses of the
show-management integration routes. These unit cases cover the gaps a checker found
after the first version: JSON documents embedded in strings, secret key names beyond
an exact list (normalized, with Unicode and digit look-alikes), and secret-shaped
values under innocuous keys (authorization values, header pair lists, connection
strings, URL fragments, webhook paths, random-looking tokens, token usernames, raw
``@``/``/`` in URL passwords, relative URLs). Over-redaction is preferred; the
non-secret controls pin what must stay readable. Every value is synthetic.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable

import pytest

from app import show_output_safety as safety
from app.show_output_safety import (
    MAX_KEY_CHARS,
    MAX_SCAN_CHARS,
    REDACTED,
    redact_config_json,
)


def _redact(value: object) -> object:
    return json.loads(redact_config_json(json.dumps(value)))


# --- secret key names -------------------------------------------------------------------

SECRET_KEYS = [
    "password",
    "passphrase",
    "pass",
    "pwd",
    "smtp_pass",
    "smtpPass",
    "db_pwd",
    "basic_auth",
    "auth",
    "key",
    "keys",
    "session",
    "sessionId",
    "sid",
    "jwt",
    "pin",
    "otp",
    "otp_seed",
    "token",
    "refresh-token",
    "secret",
    "client_secret",
    "clientSecret",
    "api_key",
    "apikey",
    "X-Api-Key",
    "private_key",
    "credential",
    "Credentials",
    "signature",
    "sig",
    "bearer",
    "cookie",
    "Set-Cookie",
    "webhook",
    "webhook_url",
    "hmac_key",
]
# Look-alike spellings: fullwidth (NFKC), Cyrillic/Greek letters, a zero-width joiner,
# digit substitutions, and case/separator variants.
LOOKALIKE_SECRET_KEYS = [
    "ｐａｓｓｗｏｒｄ",  # fullwidth
    "раssword",  # Cyrillic "р" and "а"
    "tοken",  # Greek omicron
    "sеcret",  # Cyrillic "е"
    "pass\u200bword",  # zero-width space
    "passw0rd",
    "t0ken",
    "s3cret",
    "API__KEY",
    "Pass-Phrase",
]


@pytest.mark.parametrize("key", SECRET_KEYS + LOOKALIKE_SECRET_KEYS)
def test_secret_key_names_are_masked(key):
    redacted = _redact({key: "synthetic-value", "nested": {key: {"deep": 1}}})
    assert redacted == {key: REDACTED, "nested": {key: REDACTED}}


@pytest.mark.parametrize(
    "key",
    [
        "username",
        "user",
        "author",
        "keyring",
        "host",
        "endpoint",
        "channel",
        "display_name",
        "enabled_events",
        "timeout_seconds",
    ],
)
def test_ordinary_key_names_stay_readable(key):
    assert _redact({key: "readable"}) == {key: "readable"}


# --- JSON embedded in strings -----------------------------------------------------------


def test_json_documents_inside_strings_are_redacted_recursively():
    inner = {"password": "synthetic-inner-pw", "nested": json.dumps({"api_key": "k1"})}
    redacted = _redact(
        {"settings": json.dumps(inner), "list": json.dumps([{"token": "t"}])}
    )
    settings = json.loads(redacted["settings"])
    assert settings["password"] == REDACTED
    assert json.loads(settings["nested"]) == {"api_key": REDACTED}
    assert json.loads(redacted["list"]) == [{"token": REDACTED}]


def test_double_encoded_top_level_string_is_redacted_and_keeps_its_encoding():
    stored = json.dumps(json.dumps({"password": "synthetic-pw", "port": 587}))
    out = redact_config_json(stored)
    assert "synthetic-pw" not in out
    assert json.loads(json.loads(out)) == {"password": REDACTED, "port": 587}


def test_non_json_text_starting_with_a_bracket_is_left_as_text():
    assert _redact({"note": "[draft] check the hall"}) == {
        "note": "[draft] check the hall"
    }


# --- secret-shaped values under any key --------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("use Bearer abc.def-ghi for calls", "use Bearer *** for calls"),
        ("Authorization: Basic dXNlcjpwYXNz", "Authorization: ***"),
        ("token Zm9vYmFyOmJhejEyMw==", "token ***"),
        (
            "Server=db.example.invalid;User ID=bob;Password=p@ss/w0rd;Database=show",
            "Server=db.example.invalid;User ID=bob;Password=***;Database=show",
        ),
        ("Data Source=x;pwd={a;b};", "Data Source=x;pwd=***;"),
        ('{"password": "broken json', '{"password": ***'),
        ("my password: hunter2", "my password: ***"),
        (
            "https://app.example.invalid/cb#access_token=tok&state=ok",
            "https://app.example.invalid/cb#access_token=***&state=ok",
        ),
        (
            "https://hooks.slack.com/services/T000/B000/XXXXXXXX",
            "https://hooks.slack.com/services/***",
        ),
        (
            "https://discord.com/api/webhooks/123/abcDEF_ghi",
            "https://discord.com/api/webhooks/***",
        ),
        (
            "https://api.telegram.org/bot123456:ABC-DEF/sendMessage",
            "https://api.telegram.org/bot***/sendMessage",
        ),
        (
            "https://org.webhook.office.com/webhookb2/guid@guid/IncomingWebhook/x/y",
            "https://org.webhook.office.com/webhookb2/***",
        ),
        (
            "https://hooks.zapier.com/hooks/catch/123/abc/",
            "https://hooks.zapier.com/hooks/catch/***",
        ),
        (
            "https://example.invalid/hook/9f86d081884c7d659a2feaa0c55ad015a3bf4f1b",
            "https://example.invalid/hook/***",
        ),
        (
            "https://acct.blob.core.windows.net/c?sv=2020-08-04&sig=abc%2Fdef",
            "https://acct.blob.core.windows.net/c?sv=2020-08-04&sig=***",
        ),
        (
            "https://ghp_synthetic0token@github.com/org/repo",
            "https://***@github.com/org/repo",
        ),
        (
            "https://u:p@ss/w@rd@host.example.invalid/path",
            "https://u:***@host.example.invalid/path",
        ),
        (
            "smtp://mailer:pw@smtp.example.invalid",
            "smtp://mailer:***@smtp.example.invalid",
        ),
        ("/hooks/in?channel=a&token=zzz", "/hooks/in?channel=a&token=***"),
        ("synthetic_Q7xL2mZ9aB4cD8eF1gH5", REDACTED),
        ("3f2a9c4e-1b7d-4e8a-9f3c-2d5e6a7b8c9d", REDACTED),
        # the whole credential after an auth scheme, not only the scheme word
        ("Authorization: token abcdefghijklmnop", "Authorization: ***"),
        ("Authorization: Basic x", "Authorization: ***"),
        ("authorization=Bearer abc", "authorization=***"),
        # space-separated secrets: netrc and command lines
        (
            "machine h.example.invalid login u password hunter2",
            "machine h.example.invalid login u password ***",
        ),
        ("cmd --password hunter2 --verbose", "cmd --password *** --verbose"),
        ("cmd -token 'a b' next", "cmd -token *** next"),
        # a token username in any scheme
        ("ftp://tok123@host.example.invalid/f", "ftp://***@host.example.invalid/f"),
    ],
)
def test_secret_shaped_values_are_masked_under_any_key(value, expected):
    assert _redact({"note": value}) == {"note": expected}


def test_short_header_tuples_keep_only_the_secret_name():
    redacted = _redact(
        {
            "h3": ["Authorization", "Bearer", "synthetic-x"],
            "h4": ["Cookie", "a", "b", "c"],
            "fields": ["region", "zone"],
            "long": ["token", "a", "b", "c", "d"],
            "nested": ["password", {"x": 1}],
        }
    )
    assert redacted == {
        "h3": ["Authorization", REDACTED, REDACTED],
        "h4": ["Cookie", REDACTED, REDACTED, REDACTED],
        "fields": ["region", "zone"],
        # Not a header tuple, but an odd-length flat name/value list: the value
        # after the secret name is masked (over-redaction is preferred).
        "long": ["token", REDACTED, "b", "c", "d"],
        # A nested value after a secret name is masked whole.
        "nested": ["password", REDACTED],
    }


def test_overlong_keys_are_secret_shaped_and_never_normalized():
    long_key = "A" * (MAX_KEY_CHARS + 1)
    redacted = _redact(
        {
            long_key: "synthetic-value",
            "pair": [long_key, "synthetic-value"],
            "field": {"name": long_key, "value": "synthetic-value"},
            "A" * MAX_KEY_CHARS: "readable",
        }
    )
    assert redacted[long_key] == REDACTED
    # not a header tuple (the name is too long): each element is redacted on its own
    assert redacted["pair"] == [long_key, "synthetic-value"]
    assert redacted["field"]["value"] == REDACTED
    assert redacted["A" * MAX_KEY_CHARS] == "readable"


def test_long_free_text_is_masked_whole_but_embedded_json_is_still_redacted():
    long_text = "note " * (MAX_SCAN_CHARS // 5 + 1)
    embedded = json.dumps(
        {"password": "synthetic-pw", "text": "x" * (MAX_SCAN_CHARS + 1)}
    )
    redacted = _redact({"long": long_text, "short": "note", "doc": embedded})
    assert redacted["long"] == REDACTED
    assert redacted["short"] == "note"
    assert json.loads(redacted["doc"]) == {"password": REDACTED, "text": REDACTED}


def test_header_pair_lists_and_name_value_objects_are_masked():
    redacted = _redact(
        {
            "headers": [["Authorization", "Bearer x"], ["Accept", "application/json"]],
            "fields": [
                {"name": "X-Api-Key", "value": "synthetic-k"},
                {"key": "Cookie", "value": "sid=1"},
                {"name": "Accept", "value": "text/plain"},
            ],
        }
    )
    assert redacted == {
        "headers": [["Authorization", REDACTED], ["Accept", "application/json"]],
        "fields": [
            {"name": "X-Api-Key", "value": REDACTED},
            {"key": "Cookie", "value": REDACTED},
            {"name": "Accept", "value": "text/plain"},
        ],
    }


@pytest.mark.parametrize(
    "value",
    [
        "smtp.example.invalid",
        "https://hooks.example.invalid/in?channel=show",
        "https://host.example.invalid:8443/path",
        "https://medium.example.invalid/@member",
        "application/json",
        "entry.created",
        "2027-03-12T08:00:00",
        "Basic setup required",
        "synthetic.uploader@example.invalid",
        "Spring Orchid Show",
    ],
)
def test_ordinary_values_stay_readable(value):
    assert _redact({"note": value}) == {"note": value}


def test_no_synthetic_secret_survives_a_mixed_config():
    secrets = [
        "synthetic-nested-password",
        "synthetic-bearer-cred",
        "synthetic-conn-pw",
        "synthetic-frag-token",
        "Zm9vYmFyOmJhejEyMw",
        "9f86d081884c7d659a2feaa0c55ad015",
    ]
    config = {
        "a": json.dumps({"db": {"password": secrets[0]}}),
        "b": [["authorization", f"Bearer {secrets[1]}"]],
        "c": f"Host=x;Password={secrets[2]};",
        "d": f"https://cb.example.invalid/#id_token={secrets[3]}",
        "e": f"Basic {secrets[4]}==",
        "f": f"https://example.invalid/x/{secrets[5]}",
    }
    out = redact_config_json(json.dumps(config))
    for secret in secrets:
        assert secret not in out


# --- HTTP Digest credentials in free text -------------------------------------------------

DIGEST_RESPONSE = "6629fae49393a05397450978507c4ef1"


@pytest.mark.parametrize(
    ("value", "secrets", "readable"),
    [
        (
            (
                'Authorization: Digest username="a", realm="r", nonce="n", uri="/", '
                f'qop=auth, nc=00000001, cnonce="0a4f113b", response="{DIGEST_RESPONSE}"'
            ),
            ["0a4f113b", DIGEST_RESPONSE],
            ["Authorization:"],
        ),
        (
            (
                'sent Digest username="a", realm="r", nonce="n", uri="/", '
                'response="d4c1e0f2", cnonce=0a4f113b, opaque="5ccc"'
            ),
            ["d4c1e0f2", "0a4f113b"],
            ['realm="r"', 'uri="/"', 'opaque="5ccc"', 'response="***"', "cnonce=***"],
        ),
        (
            f"retry with digest username=a, cnonce='c0ffee', response={DIGEST_RESPONSE}",
            ["c0ffee", DIGEST_RESPONSE],
            ["retry with", "cnonce='***'"],
        ),
    ],
)
def test_digest_response_and_cnonce_are_masked(value, secrets, readable):
    out = _redact({"note": value})["note"]
    for secret in secrets:
        assert secret not in out
    for text in readable:
        assert text in out


@pytest.mark.parametrize(
    "value",
    [
        "Digest summary sent to members",
        "https://api.example.invalid/v1?response=json&format=digest",
        "response: accepted",
    ],
)
def test_digest_words_without_a_digest_credential_stay_readable(value):
    assert _redact({"note": value, "response_format": "json"}) == {
        "note": value,
        "response_format": "json",
    }


# --- curl -u user:password ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (
            "curl -u alice:Tr0ub4dor https://api.example.invalid/v1",
            "curl -u alice:*** https://api.example.invalid/v1",
        ),
        ("curl --user alice:Tr0ub4dor -X GET", "curl --user alice:*** -X GET"),
        ("curl --user=alice:Tr0ub4dor", "curl --user=alice:***"),
        ('curl -u "alice:Tr0ub 4dor" -s', 'curl -u "alice:***" -s'),
        ("curl -u 'alice:Tr0ub4dor' -s", "curl -u 'alice:***' -s"),
        ("curl -ualice:Tr0ub4dor -s", "curl -ualice:*** -s"),
        ("curl -su alice:Tr0ub4dor -s", "curl -su alice:*** -s"),
        ("curl --proxy-user bob:Tr0ub4dor", "curl --proxy-user bob:***"),
        ("curl -U bob:Tr0ub4dor", "curl -U bob:***"),
        # only the password part quoted, or quoted mid-word
        ('curl -u admin:"hunter2!" -s', "curl -u admin:*** -s"),
        ('curl --user=admin:"hunter2"', "curl --user=admin:***"),
        ("curl -u admin:'p@ss w0rd' -s", "curl -u admin:*** -s"),
        ('curl -u admin:hun"ter2" -s', "curl -u admin:*** -s"),
        ('curl -u "admin":"p w" -s', 'curl -u "admin":*** -s'),
        # an API key passed as the username with an empty password
        (
            "curl -u sk_synthetic: https://x.example.invalid",
            "curl -u ***: https://x.example.invalid",
        ),
    ],
)
def test_cli_user_passwords_are_masked(value, expected):
    assert _redact({"note": value}) == {"note": expected}


@pytest.mark.parametrize(
    "value",
    [
        "curl -u alice https://api.example.invalid/v1",
        "mysql --user=root --host=db.example.invalid",
        "psql -U postgres -h db.example.invalid",
        "curl -X POST https://api.example.invalid/v1/items",
        "re-use the user:agent value",
    ],
)
def test_cli_commands_without_a_password_stay_readable(value):
    assert _redact({"note": value}) == {"note": value}


# --- header lists of any length ---------------------------------------------------------------

HEADER_LINES = [
    "Accept: application/json",
    "Content-Type: application/json",
    "User-Agent: orchid-show",
    "X-Request-Id: 12",
]


def test_flat_name_value_header_lists_mask_every_secret_value():
    raw = [
        "Accept", "application/json",
        "User-Agent", "orchid-show",
        "X-Api-Key", "synthetic-api-key",
        "Via", "proxy",
        "Authorization", "Bearer synthetic-bearer",
    ]  # fmt: skip
    short = ["Accept", "a", "X-Api-Key", "synthetic-short-key"]
    assert _redact({"raw": raw, "short": short}) == {
        "raw": [
            "Accept", "application/json",
            "User-Agent", "orchid-show",
            "X-Api-Key", REDACTED,
            # "synthetic-api-key" looks like a secret name: the element after it is
            # masked too (a flat list's pairing is never inferred; fail closed)
            REDACTED, "proxy",
            "Authorization", REDACTED,
        ],
        "short": ["Accept", "a", "X-Api-Key", REDACTED],
    }  # fmt: skip


def test_header_line_lists_mask_the_secret_line_value_at_any_length():
    for lines in (
        ["Authorization: Bearer synthetic-bearer", "Accept: a"],
        ["X-Api-Key: synthetic key part2", *HEADER_LINES],
        [*HEADER_LINES, "Authorization: Bearer synthetic bearer part2"],
    ):
        out = _redact({"headers": lines})["headers"]
        assert "synthetic" not in json.dumps(out)
        assert [line for line in out if REDACTED not in line] == [
            line
            for line in lines
            if line.split(":")[0] not in {"Authorization", "X-Api-Key"}
        ]


def test_multi_line_header_blocks_mask_whole_secret_values():
    block = "\r\n".join(
        [*HEADER_LINES, "X-Api-Key: synthetic key part2", "Authorization: Bearer a b"]
    )
    out = _redact({"raw": block})["raw"]
    assert out.split("\r\n") == [*HEADER_LINES, "X-Api-Key: ***", "Authorization: ***"]


def test_cli_header_arguments_mask_the_whole_quoted_value():
    command = (
        "curl -H 'Accept: a' -H 'B: b' -H 'C: c' -H 'D: d' "
        "-H 'X-Api-Key: synthetic key part2' --header \"Authorization: Bearer x y\""
    )
    assert _redact({"cmd": command}) == {
        "cmd": "curl -H 'Accept: a' -H 'B: b' -H 'C: c' -H 'D: d' "
        "-H 'X-Api-Key: ***' --header \"Authorization: ***\""
    }


@pytest.mark.parametrize(
    "value",
    [
        ["Accept", "application/json", "User-Agent", "orchid", "Via", "proxy"],
        HEADER_LINES + ["Cache-Control: no-cache"],
        ["region", "zone", "alpha", "beta", "gamma", "delta"],
        "\n".join(HEADER_LINES),
        "curl -H 'Accept: application/json' https://api.example.invalid/v1",
    ],
)
def test_header_lists_without_secrets_stay_readable(value):
    assert _redact({"headers": value}) == {"headers": value}


def test_partly_quoted_cli_passwords_never_leak():
    for value in (
        'curl -u admin:"hunter2!" https://x.example.invalid',
        "curl --user=admin:'p@ss w0rd'",
        "curl -u admin:hun\"ter2\"x'yz' -s",
    ):
        out = _redact({"note": value})["note"]
        assert "hunter2" not in out and "p@ss" not in out and "ter2" not in out
        assert "admin:***" in out


def test_flat_header_lists_treat_null_as_a_value():
    raw = ["Accept", "a", "X-Api-Key", "synthetic-key", "Via", None]
    # "synthetic-key" itself looks like a secret name, so the element after it is
    # masked too (fail closed: a flat list's pairing is never inferred).
    assert _redact({"raw": raw}) == {
        "raw": ["Accept", "a", "X-Api-Key", REDACTED, REDACTED, None]
    }


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("  X-Auth-Token : a b", "  X-Auth-Token : ***"),
        ("password = hunter2", "password = ***"),
        ("--password : hunter2", "--password : ***"),
    ],
)
def test_spaced_separators_are_kept_and_the_value_is_masked(value, expected):
    assert _redact({"note": value}) == {"note": expected}


@pytest.mark.parametrize(
    "tail",
    ["tailsecret -s", '"Zq9 sEcr" -s', '"Zq9\tsEcr" -s', "'Zq9\nsEcr' -s\nnext"],
)
def test_cli_user_words_past_the_segment_bound_mask_the_rest_of_the_text(tail):
    # a quoted space, tab or line break past the bound must not end the masking
    value = "curl -u admin:" + "a''" * 32 + tail
    assert _redact({"note": value}) == {"note": "curl -u ***"}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        # a value that crosses a line break masks to the end of the text: its
        # quotes may belong to a later command
        ("curl -u admin:'Zq9\nsEcr' -s\nnext", "curl -u admin:***"),
        ('curl -u admin:"Zq9\r\nsEcr" -s', "curl -u admin:***"),
        ('curl -u "admin:Zq9\nsEcr" -s', 'curl -u "admin:***'),
        # an unterminated quote runs to the end of the text
        ("curl -u admin:'Zq9\nsEcr -s\nmore", "curl -u admin:***"),
    ],
)
def test_cli_user_quoted_passwords_spanning_lines_are_masked(value, expected):
    assert _redact({"note": value}) == {"note": expected}


# ======================================================================================
# Remaining owner-view redaction gaps (Release 1 ledger), and checker round 1.
#
# Owner-view ``config_json`` redaction: remaining gaps (Release 1 ledger).
#
# ``app.show_output_safety.redact_config_json`` masks secrets in the owner-only
# show-integration responses. These cases close the gaps left after the Digest,
# ``curl -u`` and header-list rounds:
#
# * one ``-u`` value with an unterminated quote swallowed the opening quote of a later
#   ``-u`` password, so the later password's tail was printed; a value that crosses a
#   line break, reaches an unterminated quote or contains another credential flag now
#   masks to the end of the text;
# * an unquoted ``\`` line continuation inside a ``-u`` password;
# * HTTPie ``-a user:pw`` / ``--auth user:pw`` / ``--auth=user:pw``;
# * odd-length flat header lists, and flat lists whose values are nested lists/objects;
# * Digest ``response``/``cnonce`` stored as dict keys beside a ``"Digest"`` value;
# * ``password =`` followed by more than 8 whitespace characters, and doubled
#   separators (``password ==``, ``password = =``).
#
# Every result must stay valid JSON, redaction must be idempotent, and every new pattern
# is linear (64 KiB and 256 KiB hostile inputs). Every value is synthetic.
# ======================================================================================

SECRET = "Zq9sEcr"  # appears in no expected output


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
