"""Read-only Gmail collector for Calyx external intelligence.

The collector searches only for configured intelligence messages, reads them,
and sends them through the same canonical email intake service used by the API.
It never marks mail read, archives, labels, deletes, replies, or sends messages.
"""

from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
from datetime import datetime
from email.utils import parseaddr, parsedate_to_datetime
import json
import os
from typing import Any, Protocol

from .email_service import ingest_external_intelligence_email
from .html_links import merge_plain_with_html_links

GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
DEFAULT_TWIN_SENDER = "twin@twin-mail.com"
DEFAULT_SUBJECT_PREFIX = "Orchid Continuum Daily Briefing"
DEFAULT_QUERY = f'from:{DEFAULT_TWIN_SENDER} subject:"{DEFAULT_SUBJECT_PREFIX}" newer_than:14d'


@dataclass(frozen=True)
class GmailIntelligenceMessage:
    gmail_id: str
    thread_id: str | None
    sender: str
    subject: str
    message_id: str
    received_at: str | None
    body: str


class GmailGateway(Protocol):
    def search(self, query: str, limit: int) -> list[str]: ...
    def get(self, message_id: str) -> dict[str, Any]: ...


def _decode(data: str | None) -> str:
    if not data:
        return ""
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8", errors="replace")


def _headers(payload: dict[str, Any]) -> dict[str, str]:
    return {
        str(header.get("name") or "").lower(): str(header.get("value") or "")
        for header in payload.get("headers", [])
        if header.get("name")
    }


def _body_parts(part: dict[str, Any]) -> tuple[list[str], list[str]]:
    plain: list[str] = []
    html: list[str] = []
    mime = str(part.get("mimeType") or "").lower()
    data = (part.get("body") or {}).get("data")
    if data:
        decoded = _decode(str(data))
        if mime == "text/plain":
            plain.append(decoded)
        elif mime == "text/html":
            html.append(decoded)
    for child in part.get("parts", []) or []:
        child_plain, child_html = _body_parts(child)
        plain.extend(child_plain)
        html.extend(child_html)
    return plain, html


def parse_gmail_message(message: dict[str, Any]) -> GmailIntelligenceMessage:
    payload = message.get("payload") or {}
    headers = _headers(payload)
    plain, html = _body_parts(payload)
    plain_text = "\n\n".join(value.strip() for value in plain if value.strip()).strip()
    html_text = "\n".join(value for value in html if value.strip())
    body = merge_plain_with_html_links(plain_text, html_text).strip()
    if not body:
        body = str(message.get("snippet") or "").strip()

    sender = parseaddr(headers.get("from", ""))[1].strip().lower()
    subject = headers.get("subject", "").strip()
    internet_message_id = headers.get("message-id", "").strip()
    gmail_id = str(message.get("id") or "")
    stable_message_id = internet_message_id or f"gmail:{gmail_id}"
    received_at: str | None = None
    if headers.get("date"):
        try:
            received_at = parsedate_to_datetime(headers["date"]).isoformat()
        except (TypeError, ValueError, OverflowError):
            received_at = None
    if received_at is None and message.get("internalDate"):
        try:
            received_at = datetime.fromtimestamp(int(message["internalDate"]) / 1000).astimezone().isoformat()
        except (TypeError, ValueError, OverflowError):
            received_at = None

    return GmailIntelligenceMessage(
        gmail_id=gmail_id,
        thread_id=str(message.get("threadId")) if message.get("threadId") else None,
        sender=sender,
        subject=subject,
        message_id=stable_message_id,
        received_at=received_at,
        body=body,
    )


class GoogleApiGmailGateway:
    def __init__(self, service: Any, user_id: str = "me") -> None:
        self.service = service
        self.user_id = user_id

    @classmethod
    def from_environment(cls) -> "GoogleApiGmailGateway":
        try:
            import google.auth
            from google.oauth2 import credentials as user_credentials
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise RuntimeError("Google Gmail dependencies are not installed") from exc

        scopes = [GMAIL_READONLY_SCOPE]
        raw = os.getenv("GOOGLE_GMAIL_CREDENTIALS_JSON") or os.getenv("GOOGLE_GMAIL_SERVICE_ACCOUNT_JSON")
        delegated_user = os.getenv("GOOGLE_GMAIL_DELEGATED_USER")
        if raw:
            info = json.loads(raw)
            credential_type = info.get("type")
            if credential_type == "service_account":
                credentials = service_account.Credentials.from_service_account_info(info, scopes=scopes)
                if delegated_user:
                    credentials = credentials.with_subject(delegated_user)
            elif credential_type == "authorized_user":
                credentials = user_credentials.Credentials.from_authorized_user_info(info, scopes=scopes)
            else:
                raise RuntimeError("GOOGLE_GMAIL_CREDENTIALS_JSON must be authorized_user or service_account JSON")
        else:
            credentials, _ = google.auth.default(scopes=scopes)
            if delegated_user and hasattr(credentials, "with_subject"):
                credentials = credentials.with_subject(delegated_user)
        return cls(build("gmail", "v1", credentials=credentials, cache_discovery=False))

    def search(self, query: str, limit: int) -> list[str]:
        ids: list[str] = []
        token: str | None = None
        while len(ids) < limit:
            response = self.service.users().messages().list(
                userId=self.user_id,
                q=query,
                maxResults=min(100, limit - len(ids)),
                pageToken=token,
            ).execute()
            ids.extend(str(item["id"]) for item in response.get("messages", []) if item.get("id"))
            token = response.get("nextPageToken")
            if not token:
                break
        return ids[:limit]

    def get(self, message_id: str) -> dict[str, Any]:
        return self.service.users().messages().get(
            userId=self.user_id,
            id=message_id,
            format="full",
        ).execute()


def collect_twin_intelligence(
    gateway: GmailGateway,
    *,
    query: str | None = None,
    limit: int = 20,
    expected_sender: str = DEFAULT_TWIN_SENDER,
    subject_prefix: str = DEFAULT_SUBJECT_PREFIX,
) -> dict[str, Any]:
    """Read and ingest matching Twin messages; exact re-runs are idempotent downstream."""
    effective_query = query or os.getenv("CALYX_INTELLIGENCE_GMAIL_QUERY") or DEFAULT_QUERY
    expected_sender = expected_sender.strip().lower()
    imported: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    failed: list[dict[str, str]] = []

    for gmail_id in gateway.search(effective_query, limit):
        try:
            parsed = parse_gmail_message(gateway.get(gmail_id))
            if parsed.sender != expected_sender:
                skipped.append({"gmail_id": gmail_id, "reason": "SENDER_MISMATCH"})
                continue
            if not parsed.subject.startswith(subject_prefix):
                skipped.append({"gmail_id": gmail_id, "reason": "SUBJECT_MISMATCH"})
                continue
            if not parsed.body:
                skipped.append({"gmail_id": gmail_id, "reason": "EMPTY_BODY"})
                continue
            result = ingest_external_intelligence_email(
                subject=parsed.subject,
                body=parsed.body,
                sender=parsed.sender,
                message_id=parsed.message_id,
                received_at=parsed.received_at,
                imported_by="gmail-twin-readonly-collector",
            )
            imported.append({
                "gmail_id": parsed.gmail_id,
                "source_id": result["id"],
                "items_discovered": result["intelligence"]["items_discovered"],
                "canonical_graph_mutated": False,
                "external_contacted": False,
            })
        except Exception as exc:  # isolate one malformed message from the rest of the batch
            failed.append({"gmail_id": gmail_id, "reason": type(exc).__name__})

    return {
        "query": effective_query,
        "messages_found": len(imported) + len(skipped) + len(failed),
        "imported": imported,
        "skipped": skipped,
        "failed": failed,
        "mailbox_mutated": False,
        "canonical_graph_mutated": False,
        "external_contacted": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect Twin Orchid Continuum intelligence from Gmail read-only")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--query", default=None)
    args = parser.parse_args()
    gateway = GoogleApiGmailGateway.from_environment()
    result = collect_twin_intelligence(gateway, query=args.query, limit=max(1, min(args.limit, 100)))
    print(json.dumps(result, default=str, indent=2))
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
