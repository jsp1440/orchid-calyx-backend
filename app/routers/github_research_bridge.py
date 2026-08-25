"""Governed GitHub issue to Calyx research-request bridge.

The bridge is disabled by default. It accepts only signed GitHub issues
webhooks from explicitly allowlisted repositories and authors, and only when
the issue carries the configured opt-in label. Accepted issues are normalized
into the existing BUILD-051 research request store; this module does not create
another research queue or grant publication or Knowledge Graph authority.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from app.routers.owner_operations import (
    MEMORY,
    db_execute,
    log_action,
    row_list,
    utc_now,
)
from app.security import verify_owner_or_api_key

router = APIRouter(
    prefix="/api/integrations/github/research",
    tags=["Calyx GitHub Research Bridge"],
)

_DEFAULT_MAX_BYTES = 64 * 1024
_MAX_MAX_BYTES = 512 * 1024
_SUPPORTED_ACTIONS = frozenset({"opened", "edited", "labeled", "reopened"})
_TAXON_PATTERN = re.compile(r"\*([A-Z][a-z]+\s+[a-z][a-z-]+)\*")
_OUTPUTS_PATTERN = re.compile(
    r"(?ms)^## Required outputs\s*$\n(?P<body>.*?)(?=^##\s|\Z)"
)
_NUMBERED_ITEM_PATTERN = re.compile(r"(?m)^\s*\d+\.\s+(.+?)\s*$")


@dataclass(frozen=True, slots=True)
class BridgeConfig:
    enabled: bool
    webhook_secret: str
    repositories: frozenset[str]
    authors: frozenset[str]
    label: str
    max_payload_bytes: int

    @property
    def configured(self) -> bool:
        return bool(
            self.enabled
            and self.webhook_secret
            and self.repositories
            and self.authors
            and self.label
        )

    @property
    def blockers(self) -> list[str]:
        blockers: list[str] = []
        if not self.enabled:
            blockers.append("CALYX_GITHUB_RESEARCH_BRIDGE_ENABLED is not true")
        if not self.webhook_secret:
            blockers.append("CALYX_GITHUB_RESEARCH_WEBHOOK_SECRET is not configured")
        if not self.repositories:
            blockers.append("CALYX_GITHUB_RESEARCH_REPOSITORIES is empty")
        if not self.authors:
            blockers.append("CALYX_GITHUB_RESEARCH_AUTHORS is empty")
        if not self.label:
            blockers.append("CALYX_GITHUB_RESEARCH_LABEL is empty")
        return blockers


def _csv_env(name: str) -> frozenset[str]:
    return frozenset(
        item.strip() for item in os.getenv(name, "").split(",") if item.strip()
    )


def bridge_config() -> BridgeConfig:
    raw_limit = os.getenv(
        "CALYX_GITHUB_RESEARCH_MAX_PAYLOAD_BYTES", str(_DEFAULT_MAX_BYTES)
    )
    try:
        max_bytes = int(raw_limit)
    except ValueError:
        max_bytes = _DEFAULT_MAX_BYTES
    max_bytes = max(1024, min(max_bytes, _MAX_MAX_BYTES))
    return BridgeConfig(
        enabled=os.getenv("CALYX_GITHUB_RESEARCH_BRIDGE_ENABLED", "").strip().lower()
        in {"1", "true", "yes", "on"},
        webhook_secret=os.getenv("CALYX_GITHUB_RESEARCH_WEBHOOK_SECRET", ""),
        repositories=_csv_env("CALYX_GITHUB_RESEARCH_REPOSITORIES"),
        authors=_csv_env("CALYX_GITHUB_RESEARCH_AUTHORS"),
        label=os.getenv("CALYX_GITHUB_RESEARCH_LABEL", "calyx-research").strip(),
        max_payload_bytes=max_bytes,
    )


def _reject(code: str, status_code: int, *, detail: str | None = None) -> None:
    safe_detail = {"code": code}
    if detail:
        safe_detail["detail"] = detail
    raise HTTPException(status_code=status_code, detail=safe_detail)


def _verify_signature(raw_body: bytes, signature: str, secret: str) -> None:
    if not signature.startswith("sha256="):
        _reject("GITHUB_RESEARCH_SIGNATURE_REQUIRED", 401)
    expected = "sha256=" + hmac.new(
        secret.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        _reject("GITHUB_RESEARCH_SIGNATURE_INVALID", 401)


def _unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def _extract_taxa(body: str) -> list[str]:
    return _unique_strings(_TAXON_PATTERN.findall(body))


def _extract_outputs(body: str) -> list[str]:
    match = _OUTPUTS_PATTERN.search(body)
    if not match:
        return []
    return _unique_strings(_NUMBERED_ITEM_PATTERN.findall(match.group("body")))


def _priority(labels: set[str]) -> str:
    for candidate in ("critical", "high", "medium", "low"):
        if f"priority:{candidate}" in labels:
            return candidate
    return "medium"


def _normalize(payload: dict[str, Any], delivery: str) -> dict[str, Any]:
    repository = payload.get("repository")
    issue = payload.get("issue")
    sender = payload.get("sender")
    if not isinstance(repository, dict) or not isinstance(issue, dict):
        _reject("GITHUB_RESEARCH_EVENT_SHAPE_INVALID", 422)
    if not isinstance(sender, dict):
        sender = {}

    repo = str(repository.get("full_name") or "").strip()
    try:
        issue_number = int(issue.get("number"))
    except (TypeError, ValueError):
        _reject("GITHUB_RESEARCH_ISSUE_NUMBER_INVALID", 422)
    if issue_number <= 0:
        _reject("GITHUB_RESEARCH_ISSUE_NUMBER_INVALID", 422)

    title = str(issue.get("title") or "").strip()
    body = str(issue.get("body") or "").strip()
    author_obj = issue.get("user")
    author = (
        str(author_obj.get("login") or "").strip()
        if isinstance(author_obj, dict)
        else ""
    )
    labels_raw = issue.get("labels")
    labels: set[str] = set()
    if isinstance(labels_raw, list):
        for item in labels_raw:
            if isinstance(item, dict):
                name = str(item.get("name") or "").strip()
                if name:
                    labels.add(name)

    stable_source = f"{repo}#{issue_number}"
    stable_digest = hashlib.sha256(stable_source.encode("utf-8")).hexdigest()
    revision_source = "|".join(
        (stable_source, str(issue.get("updated_at") or ""), delivery)
    )
    delivery_digest = hashlib.sha256(revision_source.encode("utf-8")).hexdigest()
    request_id = f"RSR-GH-{stable_digest[:16].upper()}"
    now = utc_now()
    return {
        "id": request_id,
        "title": title,
        "research_question": body,
        "taxa": _extract_taxa(body),
        "geography": [],
        "requested_evidence_sources": [],
        "requested_outputs": _extract_outputs(body),
        "priority": _priority(labels),
        "provenance": {
            "integration": "calyx-github-research-bridge/v1",
            "source_repository": repo,
            "source_issue_number": issue_number,
            "source_issue_url": str(issue.get("html_url") or "").strip(),
            "source_issue_author": author,
            "source_issue_state": str(issue.get("state") or "").strip(),
            "source_issue_created_at": issue.get("created_at"),
            "source_issue_updated_at": issue.get("updated_at"),
            "source_issue_labels": sorted(labels),
            "github_sender": str(sender.get("login") or "").strip(),
            "github_delivery": delivery,
            "stable_intake_key": stable_digest,
            "delivery_intake_key": delivery_digest,
            "received_at": now,
        },
        "status": "queued_waiting_for_executor",
        "blocker": "No live research executor/result-return worker is activated.",
        "owner": author or "github_research_bridge",
        "created_by": "github_research_bridge",
        "created_at": now,
        "updated_at": now,
    }


def _persist_idempotently(record: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Return (record, created) using the existing research-request store."""

    def _write(cur):
        if cur is None:
            existing = next(
                (
                    item
                    for item in MEMORY["research_requests"]
                    if item.get("id") == record["id"]
                ),
                None,
            )
            if existing is not None:
                return existing, False
            MEMORY["research_requests"].insert(0, record)
            return record, True

        from psycopg.types.json import Jsonb

        cur.execute(
            """
            INSERT INTO oc_admin.build051_research_requests
                (id, payload, created_by, created_at, updated_at)
            VALUES (%s, %s, %s, NOW(), NOW())
            ON CONFLICT (id) DO NOTHING
            RETURNING payload
            """,
            (record["id"], Jsonb(record), record["created_by"]),
        )
        inserted = cur.fetchone()
        if inserted is not None:
            return dict(inserted["payload"]), True
        cur.execute(
            """
            SELECT payload
            FROM oc_admin.build051_research_requests
            WHERE id = %s
            """,
            (record["id"],),
        )
        existing = cur.fetchone()
        if existing is None:
            raise RuntimeError("GITHUB_RESEARCH_IDEMPOTENCY_READBACK_MISSING")
        return dict(existing["payload"]), False

    return db_execute(_write)


def _bridge_rows() -> list[dict[str, Any]]:
    return [
        row
        for row in row_list("research_requests")
        if isinstance(row.get("provenance"), dict)
        and row["provenance"].get("integration")
        == "calyx-github-research-bridge/v1"
    ]


@router.get("/readiness")
def readiness(
    auth: dict[str, object] = Depends(verify_owner_or_api_key),
) -> dict[str, Any]:
    del auth
    config = bridge_config()
    rows = _bridge_rows()
    counts: dict[str, int] = {}
    for row in rows:
        state = str(row.get("status") or "unknown")
        counts[state] = counts.get(state, 0) + 1
    return {
        "bridge": "calyx-github-research-bridge/v1",
        "enabled": config.enabled,
        "configured": config.configured,
        "repositories": sorted(config.repositories),
        "authors": sorted(config.authors),
        "required_label": config.label,
        "max_payload_bytes": config.max_payload_bytes,
        "webhook_secret_configured": bool(config.webhook_secret),
        "github_feedback_configured": bool(
            os.getenv("CALYX_GITHUB_RESEARCH_FEEDBACK_TOKEN", "").strip()
        ),
        "executor_status": "not_activated",
        "blockers": config.blockers
        + ["Live research executor/result-return worker is not activated."],
        "request_counts": counts,
        "total_requests": len(rows),
    }


@router.post("/issues")
async def receive_issue(request: Request) -> dict[str, Any]:
    config = bridge_config()
    if not config.configured:
        _reject(
            "GITHUB_RESEARCH_BRIDGE_NOT_CONFIGURED",
            503,
            detail="Inspect the protected readiness endpoint for activation blockers.",
        )

    event = request.headers.get("X-GitHub-Event", "")
    delivery = request.headers.get("X-GitHub-Delivery", "").strip()
    signature = request.headers.get("X-Hub-Signature-256", "")
    if event != "issues":
        _reject("GITHUB_RESEARCH_EVENT_UNSUPPORTED", 422)
    if not delivery or len(delivery) > 128:
        _reject("GITHUB_RESEARCH_DELIVERY_INVALID", 422)

    raw_body = await request.body()
    if len(raw_body) > config.max_payload_bytes:
        _reject("GITHUB_RESEARCH_PAYLOAD_TOO_LARGE", 413)
    _verify_signature(raw_body, signature, config.webhook_secret)

    try:
        payload = json.loads(raw_body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        _reject("GITHUB_RESEARCH_JSON_INVALID", 422)
    if not isinstance(payload, dict):
        _reject("GITHUB_RESEARCH_EVENT_SHAPE_INVALID", 422)

    action = str(payload.get("action") or "").strip()
    if action not in _SUPPORTED_ACTIONS:
        _reject("GITHUB_RESEARCH_ACTION_UNSUPPORTED", 422)

    record = _normalize(payload, delivery)
    provenance = record["provenance"]
    repo = str(provenance["source_repository"])
    author = str(provenance["source_issue_author"])
    labels = set(provenance["source_issue_labels"])
    if repo not in config.repositories:
        _reject("GITHUB_RESEARCH_REPOSITORY_NOT_ALLOWED", 403)
    if author not in config.authors:
        _reject("GITHUB_RESEARCH_AUTHOR_NOT_ALLOWED", 403)
    if config.label not in labels:
        _reject("GITHUB_RESEARCH_OPT_IN_LABEL_REQUIRED", 403)
    if provenance["source_issue_state"] != "open":
        _reject("GITHUB_RESEARCH_ISSUE_NOT_OPEN", 422)
    if not record["title"] or not record["research_question"]:
        _reject("GITHUB_RESEARCH_CONTENT_REQUIRED", 422)

    persisted, created = _persist_idempotently(record)
    auth = {"actor": author, "auth_type": "github_webhook_hmac"}
    log_action(
        auth,
        "github_research_request:accepted"
        if created
        else "github_research_request:duplicate",
        "research_request",
        str(persisted["id"]),
        {
            "source_repository": repo,
            "source_issue_number": provenance["source_issue_number"],
            "delivery_intake_key": provenance["delivery_intake_key"],
            "created": created,
        },
    )
    status = "queued_waiting_for_executor" if created else "duplicate"
    marker = f"<!-- calyx-research-bridge:{persisted['id']} -->"
    return {
        "status": status,
        "created": created,
        "research_request": persisted,
        "github_feedback": {
            "configured": bool(
                os.getenv("CALYX_GITHUB_RESEARCH_FEEDBACK_TOKEN", "").strip()
            ),
            "marker": marker,
            "message": (
                f"{marker}\nCalyx research request **{persisted['id']}** "
                f"was {'accepted' if created else 'already accepted'} from "
                f"**{repo}#{provenance['source_issue_number']}**. "
                "Current state: queued_waiting_for_executor."
            ),
        },
        "authority": {
            "scientific_publication": False,
            "knowledge_graph_mutation": False,
            "taxonomy_activation": False,
            "sensitive_locality_disclosure": False,
        },
    }
