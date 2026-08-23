"""Canonical transport-neutral representation of an inbound email."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any


@dataclass(frozen=True)
class InboundAttachmentMetadata:
    """Metadata only; attachment bytes remain quarantined outside this contract."""

    filename: str
    content_type: str | None = None
    size_bytes: int | None = None
    sha256: str | None = None
    provider_attachment_id: str | None = None


@dataclass(frozen=True)
class InboundEmailEnvelope:
    """Normalized inbound message.

    Message text is always data.  Neither the body nor attachments may confer
    authorization, change runtime policy, or directly establish scientific truth.
    """

    provider: str
    provider_message_id: str
    sender: str
    subject: str
    body_text: str
    recipients: tuple[str, ...]
    internet_message_id: str | None = None
    thread_id: str | None = None
    reply_to: str | None = None
    received_at: str | None = None
    attachments: tuple[InboundAttachmentMetadata, ...] = ()
    trust_metadata: dict[str, Any] = field(default_factory=dict)

    def content_sha256(self) -> str:
        """Stable digest for replay/deduplication support without trusting content."""
        canonical = "\n".join(
            (
                self.sender.strip().lower(),
                self.subject.strip(),
                self.body_text,
                "|".join(sorted(value.strip().lower() for value in self.recipients)),
            )
        )
        return sha256(canonical.encode("utf-8")).hexdigest()

    def dedupe_keys(self) -> tuple[str, ...]:
        """Return strongest available replay keys in deterministic order."""
        keys = [f"provider:{self.provider.strip().lower()}:{self.provider_message_id.strip()}"]
        if self.internet_message_id and self.internet_message_id.strip():
            keys.append(f"message-id:{self.internet_message_id.strip().lower()}")
        keys.append(f"content-sha256:{self.content_sha256()}")
        return tuple(keys)
