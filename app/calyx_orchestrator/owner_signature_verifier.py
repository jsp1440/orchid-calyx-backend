from __future__ import annotations

import base64
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

OWNER_VERIFY_KEYS_ENV = "CALYX_OWNER_VERIFY_KEYS_JSON"
OWNER_REVOKED_KEY_IDS_ENV = "CALYX_OWNER_REVOKED_KEY_IDS"
SIGNATURE_PREFIX = "ed25519"
SIGNING_DOMAIN = b"calyx-owner-grant-v1\x00"
_KEY_ID = re.compile(r"^[A-Za-z0-9._-]{1,80}$")


def owner_grant_signing_bytes(payload: Mapping[str, Any]) -> bytes:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return SIGNING_DOMAIN + encoded


def _decode_base64url(value: str, *, expected_length: int | None = None) -> bytes:
    text = value.strip()
    if not text:
        raise ValueError("OWNER_SIGNATURE_BASE64_INVALID")
    padding = "=" * (-len(text) % 4)
    try:
        decoded = base64.b64decode(text + padding, altchars=b"-_", validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("OWNER_SIGNATURE_BASE64_INVALID") from exc
    if expected_length is not None and len(decoded) != expected_length:
        raise ValueError("OWNER_SIGNATURE_LENGTH_INVALID")
    return decoded


def _normalize_key_id(value: str) -> str:
    key_id = value.strip()
    if not _KEY_ID.fullmatch(key_id):
        raise ValueError("OWNER_SIGNATURE_KEY_ID_INVALID")
    return key_id


@dataclass(frozen=True, slots=True)
class OwnerVerificationKey:
    key_id: str
    public_key: Ed25519PublicKey

    @classmethod
    def from_base64url(cls, *, key_id: str, public_key: str) -> OwnerVerificationKey:
        normalized_id = _normalize_key_id(key_id)
        raw = _decode_base64url(public_key, expected_length=32)
        return cls(key_id=normalized_id, public_key=Ed25519PublicKey.from_public_bytes(raw))


class Ed25519OwnerGrantSignatureVerifier:
    """Verify owner grants with public keys only; this type cannot sign grants."""

    def __init__(self, *, keys: Mapping[str, OwnerVerificationKey], revoked_key_ids: frozenset[str] = frozenset()) -> None:
        normalized: dict[str, OwnerVerificationKey] = {}
        for supplied_id, key in keys.items():
            key_id = _normalize_key_id(str(supplied_id))
            if key.key_id != key_id:
                raise ValueError("OWNER_SIGNATURE_KEY_ID_MISMATCH")
            if key_id in normalized:
                raise ValueError("OWNER_SIGNATURE_DUPLICATE_KEY")
            normalized[key_id] = key
        if not normalized:
            raise ValueError("OWNER_SIGNATURE_KEYRING_EMPTY")
        revoked = frozenset(_normalize_key_id(value) for value in revoked_key_ids)
        if revoked - normalized.keys():
            raise ValueError("OWNER_SIGNATURE_REVOKED_KEY_UNKNOWN")
        if len(revoked) == len(normalized):
            raise ValueError("OWNER_SIGNATURE_ALL_KEYS_REVOKED")
        self._keys = normalized
        self._revoked_key_ids = revoked

    @classmethod
    def from_environ(cls, environ: Mapping[str, str] | None = None) -> Ed25519OwnerGrantSignatureVerifier:
        source = os.environ if environ is None else environ
        raw_keys = str(source.get(OWNER_VERIFY_KEYS_ENV, "")).strip()
        if not raw_keys:
            raise RuntimeError("OWNER_SIGNATURE_KEYS_NOT_CONFIGURED")
        try:
            decoded = json.loads(raw_keys)
        except json.JSONDecodeError as exc:
            raise RuntimeError("OWNER_SIGNATURE_KEYS_INVALID") from exc
        if not isinstance(decoded, dict) or not decoded:
            raise RuntimeError("OWNER_SIGNATURE_KEYS_INVALID")
        keys: dict[str, OwnerVerificationKey] = {}
        try:
            for key_id, public_key in decoded.items():
                normalized_id = _normalize_key_id(str(key_id))
                keys[normalized_id] = OwnerVerificationKey.from_base64url(key_id=normalized_id, public_key=str(public_key))
        except (TypeError, ValueError) as exc:
            raise RuntimeError("OWNER_SIGNATURE_KEYS_INVALID") from exc
        raw_revoked = str(source.get(OWNER_REVOKED_KEY_IDS_ENV, "")).strip()
        revoked = frozenset(item.strip() for item in raw_revoked.split(",") if item.strip())
        try:
            return cls(keys=keys, revoked_key_ids=revoked)
        except ValueError as exc:
            raise RuntimeError("OWNER_SIGNATURE_KEYRING_INVALID") from exc

    def verify(self, *, payload: Mapping[str, Any], signature: str) -> bool:
        try:
            algorithm, raw_key_id, encoded_signature = signature.split(":", 2)
            if algorithm != SIGNATURE_PREFIX:
                return False
            key_id = _normalize_key_id(raw_key_id)
            if key_id in self._revoked_key_ids:
                return False
            key = self._keys.get(key_id)
            if key is None:
                return False
            signature_bytes = _decode_base64url(encoded_signature, expected_length=64)
            key.public_key.verify(signature_bytes, owner_grant_signing_bytes(payload))
        except (InvalidSignature, TypeError, ValueError):
            return False
        return True

    @property
    def active_key_ids(self) -> tuple[str, ...]:
        return tuple(sorted(key_id for key_id in self._keys if key_id not in self._revoked_key_ids))

    @property
    def revoked_key_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._revoked_key_ids))
