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

import pytest

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
        "long": ["token", "a", "b", "c", "d"],  # not a header tuple
        "nested": ["password", {"x": 1}],
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
            "Via", "proxy",
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
    assert _redact({"raw": raw}) == {
        "raw": ["Accept", "a", "X-Api-Key", REDACTED, "Via", None]
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
        ("curl -u admin:'Zq9\nsEcr' -s\nnext", "curl -u admin:*** -s\nnext"),
        ('curl -u admin:"Zq9\r\nsEcr" -s', "curl -u admin:*** -s"),
        ('curl -u "admin:Zq9\nsEcr" -s', 'curl -u "admin:***" -s'),
        # an unterminated quote runs to the end of the text
        ("curl -u admin:'Zq9\nsEcr -s\nmore", "curl -u admin:***"),
    ],
)
def test_cli_user_quoted_passwords_spanning_lines_are_masked(value, expected):
    assert _redact({"note": value}) == {"note": expected}
