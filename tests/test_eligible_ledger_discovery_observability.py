from __future__ import annotations

import io
from pathlib import Path
from typing import Self
from urllib.error import HTTPError, URLError

import pytest

from scripts.discover_eligible_reasoning_ledgers import (
    DiscoveryFailure,
    _write_receipt,
    call,
    discover,
    failure_receipt,
)


class Response:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self._body = body

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def http_error(code: int) -> HTTPError:
    return HTTPError(
        "https://example.invalid/api",
        code,
        "error",
        hdrs=None,
        fp=io.BytesIO(b"{}"),
    )


def test_call_retries_transient_503_and_succeeds() -> None:
    attempts = iter(
        [
            http_error(503),
            http_error(503),
            Response(200, b'{"eligible_count":0,"eligible_ledgers":[]}'),
        ]
    )
    sleeps: list[float] = []

    def opener(*args: object, **kwargs: object) -> Response:
        item = next(attempts)
        if isinstance(item, Exception):
            raise item
        return item

    status, body = call(
        "/api/reasoning-ledgers/eligible-for-publication",
        base_url="https://example.invalid",
        opener=opener,
        sleep=sleeps.append,
    )
    assert status == 200
    assert body["eligible_count"] == 0
    assert sleeps == [1.0, 2.0]


def test_call_reports_terminal_503_after_bounded_retries() -> None:
    sleeps: list[float] = []

    def opener(*args: object, **kwargs: object) -> Response:
        raise http_error(503)

    with pytest.raises(DiscoveryFailure) as captured:
        call(
            "/api/reasoning-ledgers/eligible-for-publication",
            base_url="https://example.invalid",
            opener=opener,
            sleep=sleeps.append,
        )
    failure = captured.value
    assert failure.code == "BACKEND_HTTP_ERROR"
    assert failure.http_status == 503
    assert failure.attempts == 3
    assert sleeps == [1.0, 2.0]


def test_call_reports_network_failure_without_leaking_target_details() -> None:
    def opener(*args: object, **kwargs: object) -> Response:
        raise URLError(ConnectionRefusedError("sensitive upstream detail"))

    with pytest.raises(DiscoveryFailure) as captured:
        call(
            "/api/reasoning-ledgers/eligible-for-publication",
            base_url="https://example.invalid",
            opener=opener,
            sleep=lambda _: None,
            max_attempts=1,
        )
    failure = captured.value
    assert failure.code == "BACKEND_NETWORK_ERROR"
    assert failure.message == "backend request failed: ConnectionRefusedError"
    assert "sensitive" not in failure.message


def test_discover_success_is_read_only_and_does_not_expose_access_code() -> None:
    responses = iter(
        [
            Response(200, b'{"token":"session-secret"}'),
            Response(200, b'{"eligible_count":0,"eligible_ledgers":[]}'),
        ]
    )

    def opener(*args: object, **kwargs: object) -> Response:
        return next(responses)

    result = discover(
        base_url="https://example.invalid",
        access_code="owner-secret",
        opener=opener,
        sleep=lambda _: None,
    )
    assert result["status"] == "success"
    assert result["eligible_count"] == 0
    assert result["read_only"] is True
    assert result["production_mutation"] is False
    assert result["publication_endpoint_invoked"] is False
    rendered = str(result)
    assert "owner-secret" not in rendered
    assert "session-secret" not in rendered
    assert len(result["artifact_hash"]) == 64


def test_failure_receipt_is_structured_redacted_and_hash_bound(tmp_path: Path) -> None:
    failure = DiscoveryFailure(
        stage="http",
        code="BACKEND_HTTP_ERROR",
        message="backend returned HTTP 503",
        http_status=503,
        attempts=3,
    )
    result = failure_receipt(failure, base_url="https://example.invalid")
    assert result["status"] == "failed"
    assert result["http_status"] == 503
    assert result["eligible_count"] is None
    assert result["eligible_ledgers"] == []
    assert result["read_only"] is True
    assert result["publication_endpoint_invoked"] is False
    assert len(result["artifact_hash"]) == 64

    output = tmp_path / "receipt.json"
    _write_receipt(result, output_path=output)
    text = output.read_text(encoding="utf-8")
    assert '"failure_code": "BACKEND_HTTP_ERROR"' in text
    assert '"production_mutation": false' in text


def test_missing_access_code_yields_typed_failure() -> None:
    with pytest.raises(DiscoveryFailure) as captured:
        discover(base_url="https://example.invalid", access_code="")
    assert captured.value.code == "OWNER_ACCESS_CODE_MISSING"
    assert captured.value.stage == "configuration"
