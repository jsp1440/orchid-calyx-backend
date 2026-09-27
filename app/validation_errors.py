"""App-wide 422 handler that can always render the errors it echoes.

FastAPI's default ``RequestValidationError`` handler echoes each error's
``input`` back to the caller. Two kinds of request input cannot be rendered by
``JSONResponse`` (UTF-8, ``allow_nan=False``), so the default handler itself
raised and every JSON endpoint answered 500 instead of 422:

* a lone UTF-16 surrogate in a JSON string (``"\\ud800"``) -- pydantic reports
  ``string_unicode`` and the echoed input cannot be UTF-8 encoded;
* a non-finite number (``NaN``, ``Infinity``), which Python's JSON parser
  accepts but the response renderer refuses.

This handler returns the same ``{"detail": [...]}`` body FastAPI returns, with
the same ``type``, ``loc``, ``msg`` and ``ctx`` keys. Only values that could not
be rendered are changed: lone surrogates become U+FFFD, non-finite floats
become the strings ``"NaN"``, ``"Infinity"`` or ``"-Infinity"``, the input of a
``string_unicode`` error is not echoed, and an echoed input larger than
``MAX_ECHOED_INPUT_CHARS`` is not echoed. An ordinary 422 renders byte-for-byte
as before.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.status import HTTP_422_UNPROCESSABLE_ENTITY

MAX_ECHOED_INPUT_CHARS = 2048
_LONE_SURROGATE = re.compile("[\ud800-\udfff]")


def _renderable(value: Any) -> Any:
    """Return ``value`` with every string UTF-8 encodable and every float finite."""
    if isinstance(value, str):
        return _LONE_SURROGATE.sub("�", value)
    if isinstance(value, float) and not math.isfinite(value):
        return "NaN" if math.isnan(value) else ("Infinity" if value > 0 else "-Infinity")
    if isinstance(value, dict):
        return {_renderable(key): _renderable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_renderable(item) for item in value]
    return value


def require_strict_json(value: Any) -> Any:
    """Raise ``ValueError`` unless ``value`` can be stored and returned as strict JSON.

    For free-form ``dict[str, Any]`` request fields that are persisted and echoed
    back: pydantic does not validate the strings inside them, so a lone surrogate
    or ``NaN`` would otherwise be accepted and then break the response (or the
    PostgreSQL JSON column) with a 500. Raised inside a pydantic validator this is
    a normal 422.
    """
    try:
        json.dumps(value, ensure_ascii=False, allow_nan=False, default=str).encode("utf-8")
    except ValueError:  # UnicodeEncodeError is a ValueError
        raise ValueError("must be strict JSON: no lone surrogates or non-finite numbers") from None
    return value


def _too_large(value: Any) -> bool:
    return len(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))) > MAX_ECHOED_INPUT_CHARS


def renderable_validation_errors(errors: Any) -> list[Any]:
    """Encode ``RequestValidationError.errors()`` so ``JSONResponse`` can always render it."""
    rendered: list[Any] = []
    for error in _renderable(jsonable_encoder(errors)):
        if (
            isinstance(error, dict)
            and "input" in error
            and (error.get("type") == "string_unicode" or _too_large(error["input"]))
        ):
            error = {key: item for key, item in error.items() if key != "input"}
        rendered.append(error)
    return rendered


async def request_validation_exception_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": renderable_validation_errors(exc.errors())},
    )
