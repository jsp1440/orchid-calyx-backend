"""Provider-neutral notification, digest, acknowledgement, and escalation service."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

SCHEMA_VERSION = "calyx-notification-service/v1"
EVENT_TYPES = {
    "delivery_blocker",
    "retry",
    "dead_letter",
    "review_requested",
    "approval_stale",
    "deployment_failed",
    "deadline_approaching",
    "grant_response",
    "harvester_failure",
    "care_alert",
}
SEVERITIES = {"info", "low", "medium", "high", "critical"}
SEVERITY_RANK = {name: index for index, name in enumerate(("info", "low", "medium", "high", "critical"))}


def notification_root() -> Path:
    return Path(os.environ.get("CALYX_NOTIFICATION_WORKSPACE", "/tmp/calyx/notifications"))


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _text(value: object) -> str:
    return str(value or "").strip()


def _safe_id(value: object, code: str) -> str:
    item = _text(value)
    if not item or item in {".", ".."} or "/" in item or "\\" in item or "\x00" in item:
        raise ValueError(code)
    return item


def _owner_key(owner_id: str) -> str:
    owner = _text(owner_id)
    if not owner:
        raise ValueError("NOTIFICATION_OWNER_REQUIRED")
    return hashlib.sha256(owner.casefold().encode("utf-8")).hexdigest()[:20]


def _stable(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_stable(value).encode("utf-8")).hexdigest()


def _parse_hhmm(value: str) -> time:
    try:
        hour, minute = value.split(":", 1)
        parsed = time(int(hour), int(minute))
    except Exception as exc:
        raise ValueError("NOTIFICATION_QUIET_HOURS_INVALID") from exc
    return parsed


def _event_content(record: dict[str, Any]) -> dict[str, Any]:
    return {
        key: record[key]
        for key in (
            "schema_version",
            "event_id",
            "event_type",
            "severity",
            "recipient_id",
            "title",
            "message",
            "source_ref",
            "dedupe_key",
            "digest_group",
        )
    }


def _refresh_state_digest(event: dict[str, Any]) -> None:
    event["state_digest"] = _digest({
        "event_digest": event["event_digest"],
        "state": event["state"],
        "duplicate_count": event.get("duplicate_count", 0),
        "last_seen_at": event.get("last_seen_at"),
        "escalation_level": event.get("escalation_level", 0),
        "acknowledgement": event.get("acknowledgement"),
        "delivery_receipts": event.get("delivery_receipts", []),
        "escalation_history": event.get("escalation_history", []),
    })


class NotificationService:
    def __init__(self, workspace: Path | None = None) -> None:
        self.workspace = workspace or notification_root()

    def _root(self, owner_id: str) -> Path:
        root = self.workspace / "owners" / _owner_key(owner_id)
        root.mkdir(parents=True, exist_ok=True)
        return root

    @staticmethod
    def _write(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")
        return payload

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(path.stem)
        return json.loads(path.read_text(encoding="utf-8"))

    def save_preferences(self, owner_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        recipient_id = _safe_id(payload.get("recipient_id"), "NOTIFICATION_RECIPIENT_ID_INVALID")
        timezone = _text(payload.get("timezone")) or "UTC"
        try:
            ZoneInfo(timezone)
        except Exception as exc:
            raise ValueError("NOTIFICATION_TIMEZONE_INVALID") from exc
        quiet_hours = dict(payload.get("quiet_hours") or {})
        if quiet_hours:
            _parse_hhmm(_text(quiet_hours.get("start")))
            _parse_hhmm(_text(quiet_hours.get("end")))
        record = {
            "schema_version": SCHEMA_VERSION,
            "recipient_id": recipient_id,
            "timezone": timezone,
            "quiet_hours": quiet_hours,
            "minimum_severity": _text(payload.get("minimum_severity")) or "info",
            "digest_enabled": bool(payload.get("digest_enabled", True)),
            "digest_group": _text(payload.get("digest_group")) or "default",
            "channels": sorted({_text(item) for item in payload.get("channels", ["in_app"]) if _text(item)}),
            "external_delivery_authorized": False,
            "provider_secret_storage_authorized": False,
            "updated_at": _now(),
        }
        if record["minimum_severity"] not in SEVERITIES:
            raise ValueError("NOTIFICATION_SEVERITY_INVALID")
        if any(channel != "in_app" for channel in record["channels"]):
            raise ValueError("NOTIFICATION_EXTERNAL_CHANNEL_NOT_AUTHORIZED")
        return self._write(self._root(owner_id) / "preferences" / f"{recipient_id}.json", record)

    def _preference(self, owner_id: str, recipient_id: str) -> dict[str, Any]:
        path = self._root(owner_id) / "preferences" / f"{_safe_id(recipient_id, 'NOTIFICATION_RECIPIENT_ID_INVALID')}.json"
        if path.exists():
            return self._read(path)
        return self.save_preferences(owner_id, {"recipient_id": recipient_id})

    def create_event(self, owner_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        event_id = _safe_id(payload.get("event_id"), "NOTIFICATION_EVENT_ID_INVALID")
        event_type = _text(payload.get("event_type"))
        severity = _text(payload.get("severity")) or "medium"
        recipient_id = _safe_id(payload.get("recipient_id"), "NOTIFICATION_RECIPIENT_ID_INVALID")
        if event_type not in EVENT_TYPES:
            raise ValueError("NOTIFICATION_EVENT_TYPE_INVALID")
        if severity not in SEVERITIES:
            raise ValueError("NOTIFICATION_SEVERITY_INVALID")
        title = _text(payload.get("title"))
        message = _text(payload.get("message"))
        if not title or not message:
            raise ValueError("NOTIFICATION_CONTENT_REQUIRED")
        source_ref = _text(payload.get("source_ref")) or None
        dedupe_key = _text(payload.get("dedupe_key")) or _digest({
            "event_type": event_type,
            "recipient_id": recipient_id,
            "source_ref": source_ref,
            "title": title,
        })
        preference = self._preference(owner_id, recipient_id)
        record = {
            "schema_version": SCHEMA_VERSION,
            "event_id": event_id,
            "event_type": event_type,
            "severity": severity,
            "recipient_id": recipient_id,
            "title": title,
            "message": message,
            "source_ref": source_ref,
            "dedupe_key": dedupe_key,
            "digest_group": _text(payload.get("digest_group")) or preference["digest_group"],
            "state": "pending",
            "duplicate_count": 0,
            "escalation_level": 0,
            "acknowledgement": None,
            "delivery_receipts": [],
            "external_delivery_authorized": False,
            "autonomous_commitment_authorized": False,
            "provider_send_authorized": False,
            "created_at": _now(),
            "last_seen_at": _now(),
        }
        record["event_digest"] = _digest(_event_content(record))
        _refresh_state_digest(record)
        events_dir = self._root(owner_id) / "events"
        event_path = events_dir / f"{event_id}.json"
        if event_path.exists():
            existing = self._read(event_path)
            if existing.get("event_digest") != record["event_digest"]:
                raise ValueError("NOTIFICATION_IMMUTABLE_EVENT_CONFLICT")
            return existing
        if events_dir.exists():
            for path in sorted(events_dir.glob("*.json")):
                existing = self._read(path)
                if existing["dedupe_key"] == dedupe_key and existing["state"] not in {"acknowledged", "closed"}:
                    existing["duplicate_count"] = int(existing.get("duplicate_count", 0)) + 1
                    existing["last_seen_at"] = _now()
                    _refresh_state_digest(existing)
                    self._write(path, existing)
                    return existing
        return self._write(event_path, record)

    def is_quiet_hours(self, preference: dict[str, Any], at: datetime | None = None) -> bool:
        quiet = dict(preference.get("quiet_hours") or {})
        if not quiet:
            return False
        zone = ZoneInfo(preference.get("timezone") or "UTC")
        current = (at or datetime.now(UTC)).astimezone(zone).time().replace(tzinfo=None)
        start = _parse_hhmm(str(quiet["start"]))
        end = _parse_hhmm(str(quiet["end"]))
        if start < end:
            return start <= current < end
        return current >= start or current < end

    def pending_for_recipient(self, owner_id: str, recipient_id: str, *, at: datetime | None = None) -> dict[str, Any]:
        preference = self._preference(owner_id, recipient_id)
        threshold = SEVERITY_RANK[preference["minimum_severity"]]
        events_dir = self._root(owner_id) / "events"
        items = []
        if events_dir.exists():
            for path in sorted(events_dir.glob("*.json")):
                event = self._read(path)
                if event["recipient_id"] == recipient_id and event["state"] == "pending" and SEVERITY_RANK[event["severity"]] >= threshold:
                    items.append(event)
        quiet = self.is_quiet_hours(preference, at=at)
        immediate = [item for item in items if item["severity"] == "critical" or not quiet]
        deferred = [item for item in items if item not in immediate]
        return {
            "schema_version": SCHEMA_VERSION,
            "recipient_id": recipient_id,
            "quiet_hours_active": quiet,
            "immediate": immediate,
            "deferred": deferred,
            "external_delivery_authorized": False,
        }

    def digest(self, owner_id: str, recipient_id: str) -> dict[str, Any]:
        preference = self._preference(owner_id, recipient_id)
        if not preference["digest_enabled"]:
            return {
                "schema_version": SCHEMA_VERSION,
                "recipient_id": recipient_id,
                "groups": {},
                "event_count": 0,
                "digest_enabled": False,
                "provider_send_authorized": False,
            }
        pending = self.pending_for_recipient(owner_id, recipient_id)
        groups: dict[str, list[dict[str, Any]]] = {}
        for event in pending["immediate"] + pending["deferred"]:
            groups.setdefault(event["digest_group"], []).append(event)
        ordered_groups = {
            key: sorted(value, key=lambda item: (-SEVERITY_RANK[item["severity"]], item["event_id"]))
            for key, value in sorted(groups.items())
        }
        return {
            "schema_version": SCHEMA_VERSION,
            "recipient_id": recipient_id,
            "groups": ordered_groups,
            "event_count": sum(len(value) for value in ordered_groups.values()),
            "digest_enabled": True,
            "provider_send_authorized": False,
        }

    def acknowledge(self, owner_id: str, event_id: str, *, actor: str, note: str | None = None) -> dict[str, Any]:
        safe_id = _safe_id(event_id, "NOTIFICATION_EVENT_ID_INVALID")
        path = self._root(owner_id) / "events" / f"{safe_id}.json"
        event = self._read(path)
        event["state"] = "acknowledged"
        event["acknowledgement"] = {"actor": _text(actor), "note": _text(note) or None, "at": _now()}
        _refresh_state_digest(event)
        return self._write(path, event)

    def escalate(self, owner_id: str, event_id: str, *, actor: str, rationale: str) -> dict[str, Any]:
        if not _text(rationale):
            raise ValueError("NOTIFICATION_ESCALATION_RATIONALE_REQUIRED")
        safe_id = _safe_id(event_id, "NOTIFICATION_EVENT_ID_INVALID")
        path = self._root(owner_id) / "events" / f"{safe_id}.json"
        event = self._read(path)
        if event["state"] == "acknowledged":
            raise ValueError("NOTIFICATION_ACKNOWLEDGED_EVENT_CANNOT_ESCALATE")
        event["escalation_level"] = int(event.get("escalation_level", 0)) + 1
        history = list(event.get("escalation_history") or [])
        history.append({"level": event["escalation_level"], "actor": _text(actor), "rationale": _text(rationale), "at": _now()})
        event["escalation_history"] = history
        _refresh_state_digest(event)
        return self._write(path, event)

    def record_delivery_receipt(self, owner_id: str, event_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        safe_id = _safe_id(event_id, "NOTIFICATION_EVENT_ID_INVALID")
        provider = _text(payload.get("provider"))
        if provider not in {"in_app_fixture", "provider_neutral_fixture"}:
            raise ValueError("NOTIFICATION_LIVE_PROVIDER_NOT_AUTHORIZED")
        path = self._root(owner_id) / "events" / f"{safe_id}.json"
        event = self._read(path)
        receipt = {
            "provider": provider,
            "provider_message_id": _text(payload.get("provider_message_id")) or None,
            "status": _text(payload.get("status")) or "recorded",
            "recorded_at": _now(),
            "live_provider_send": False,
        }
        event["delivery_receipts"] = list(event.get("delivery_receipts") or []) + [receipt]
        _refresh_state_digest(event)
        return self._write(path, event)

    def readiness(self, owner_id: str) -> dict[str, Any]:
        events_dir = self._root(owner_id) / "events"
        events = [self._read(path) for path in sorted(events_dir.glob("*.json"))] if events_dir.exists() else []
        pending = [item for item in events if item["state"] == "pending"]
        critical = [item for item in pending if item["severity"] == "critical"]
        return {
            "schema_version": SCHEMA_VERSION,
            "event_count": len(events),
            "pending_count": len(pending),
            "critical_pending_count": len(critical),
            "deduplication_enabled": True,
            "quiet_hours_supported": True,
            "digest_grouping_supported": True,
            "external_delivery_authorized": False,
            "unsolicited_external_messaging_authorized": False,
            "autonomous_commitment_authorized": False,
            "provider_secret_storage_authorized": False,
            "live_provider_send_authorized": False,
            "deployment_authorized": False,
        }
