"""The hosted verifier accepts real-world pasted DSNs and never echoes them."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

REPO_ROOT = Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location(
        "oc_autonomy_hosted_verify",
        REPO_ROOT / "scripts" / "oc_autonomy_hosted_verify.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HOST = "ep-x-123.us-west-2.aws.neon.tech"
PLAIN = f"postgresql://oc_verify:s3cret@{HOST}/neondb?sslmode=require"


@pytest.mark.parametrize(
    "raw",
    [
        PLAIN,
        f"  {PLAIN}\n",
        f"'{PLAIN}'",
        f"psql '{PLAIN}'",
        PLAIN.replace("postgresql://", "postgres://"),
    ],
)
def test_pasted_forms_normalize_to_a_parseable_url(raw):
    url = make_url(_module().normalize_dsn(raw))
    assert (url.drivername, url.username, url.password) == (
        "postgresql",
        "oc_verify",
        "s3cret",
    )
    assert (url.host, url.database, url.query["sslmode"]) == (
        HOST,
        "neondb",
        "require",
    )


def test_reserved_characters_in_the_password_are_encoded():
    raw = f"postgresql://oc_verify:p@ss#w/rd?x:y@{HOST}/neondb?sslmode=require"
    url = make_url(_module().normalize_dsn(raw))
    assert url.password == "p@ss#w/rd?x:y"
    assert url.host == HOST and url.database == "neondb"


def test_already_encoded_password_is_not_double_encoded():
    raw = f"postgresql://oc_verify:p%40ss@{HOST}/neondb"
    assert make_url(_module().normalize_dsn(raw)).password == "p@ss"


def test_unparseable_dsn_reports_shape_not_value(capsys, monkeypatch):
    module = _module()
    monkeypatch.setattr(
        "sys.argv", ["verify", "--dsn", "not a url with secret-value-123"]
    )
    assert module.main() == 1
    out = capsys.readouterr().out
    assert "VERIFY_DSN_UNPARSEABLE" in out
    assert "secret-value-123" not in out
