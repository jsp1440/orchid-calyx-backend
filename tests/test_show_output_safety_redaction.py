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

from app.show_output_safety import REDACTED, redact_config_json


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
        ("Authorization: Basic dXNlcjpwYXNz", "Authorization: *** ***"),
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
    ],
)
def test_secret_shaped_values_are_masked_under_any_key(value, expected):
    assert _redact({"note": value}) == {"note": expected}


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
