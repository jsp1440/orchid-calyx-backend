"""Deterministic external-intelligence assimilation planning.

This module turns external intelligence summaries (for example a Twin daily
briefing) into bounded, provenance-preserving candidate items.  It does not
fetch external URLs, mutate canonical scientific stores, publish to the
Knowledge Graph, contact partners, or submit grants.
"""

from __future__ import annotations

from hashlib import sha256
import re
from typing import Iterable

from .schemas import IntakeTask

INTELLIGENCE_PARSER_VERSION = "calyx-intelligence-intake-v1"

SECTION_DOMAINS = {
    "Funding and Grants": "funding",
    "Research and Publications": "research",
    "Taxonomy Updates": "taxonomy",
    "Conservation News": "conservation",
    "Partnership Opportunities": "partnerships",
    "Technology and Infrastructure Opportunities": "technology",
}

PRIORITY_RE = re.compile(r"\s+(High|Medium|Low) Priority\s*$", re.I)
URL_RE = re.compile(r"https?://[^\s)>]+", re.I)
DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.I)

AUTO_INTERNAL_ACTIONS = (
    "preserve_source",
    "classify",
    "deduplicate",
    "verify_read_only",
    "compare_existing_knowledge",
    "create_candidate_record",
    "open_internal_investigation",
)

APPROVAL_REQUIRED_ACTIONS = (
    "external_contact",
    "grant_submission",
    "canonical_taxonomy_change",
    "production_knowledge_graph_publication",
    "scientific_publication",
    "sensitive_location_disclosure",
)


def canonical_email_text(
    *,
    sender: str,
    subject: str,
    body: str,
    message_id: str | None = None,
    received_at: str | None = None,
) -> str:
    """Return a stable email representation so provenance participates in hashing."""
    headers = [
        f"From: {sender.strip()}",
        f"Subject: {subject.strip()}",
    ]
    if message_id:
        headers.append(f"Message-ID: {message_id.strip()}")
    if received_at:
        headers.append(f"Received-At: {received_at.strip()}")
    headers.append("X-Orchid-Intake-Kind: external-intelligence-email")
    return "\n".join(headers) + "\n\n" + body.strip() + "\n"


def _destinations(domain: str, text: str) -> list[str]:
    lower = text.lower()
    destinations: set[str] = set()

    if domain == "funding":
        destinations.add("grant_intelligence")
    elif domain == "research":
        destinations.add("orep")
    elif domain == "taxonomy":
        destinations.add("taxonomy_reconciliation")
    elif domain == "conservation":
        destinations.add("conservation_platform")
    elif domain == "partnerships":
        destinations.add("orchid_connect")
    elif domain == "technology":
        destinations.add("source_registry")

    if any(marker in lower for marker in ("pollinator", "pollination", "pollinating")):
        destinations.add("pollinator_network")
    if any(marker in lower for marker in ("mycorrhiz", "fungal", "fungus", "fungi")):
        destinations.add("mycorrhizal_network")
    if any(marker in lower for marker in ("habitat", "remote sensing", "satellite", "earth engine", "land-use", "land use", "fire", "moisture")):
        destinations.add("atlas")
    if any(marker in lower for marker in ("trait", "morphology", "floral morphology", "phenology")):
        destinations.add("traitbank")
    if any(marker in lower for marker in ("api", "dataset", "data source", "platform", "open-source", "open source")):
        destinations.add("source_registry")

    return sorted(destinations)


def _follow_up_tasks(domain: str, text: str) -> list[str]:
    lower = text.lower()
    tasks = ["VERIFY_PRIMARY_SOURCE", "COMPARE_EXISTING_KNOWLEDGE"]

    if domain == "funding":
        tasks.append("CHECK_GRANT_ELIGIBILITY")
    if domain == "taxonomy":
        tasks.append("RECONCILE_TAXONOMY")
    if domain == "partnerships":
        tasks.append("EVALUATE_PARTNERSHIP")
    if domain == "technology" or any(marker in lower for marker in ("api", "dataset", "platform")):
        tasks.append("EVALUATE_FEDERATION")
    if "earth engine" in lower:
        tasks.append("EVALUATE_ATLAS_PROVIDER")
    if any(marker in lower for marker in ("pollinator", "pollination", "mycorrhiz", "fungal", "fungus", "fungi")):
        tasks.append("EVALUATE_RELATIONSHIP_EVIDENCE")

    return list(dict.fromkeys(tasks))


def _fingerprint(*parts: str) -> str:
    normalized = "\x1f".join(re.sub(r"\s+", " ", part.strip()).lower() for part in parts)
    return sha256(normalized.encode("utf-8")).hexdigest()


def parse_external_intelligence(
    body: str,
    *,
    sender: str = "",
    message_id: str = "",
) -> list[dict[str, object]]:
    """Parse a sectioned briefing into deterministic candidate intelligence items.

    The parser intentionally ignores Executive Summary priority repetition and
    only starts collecting items after a recognized canonical section heading.
    """
    lines = [line.strip() for line in body.splitlines()]
    items: list[dict[str, object]] = []
    current_domain: str | None = None
    current_title: str | None = None
    current_priority: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        nonlocal current_title, current_priority, buffer
        if not current_domain or not current_title:
            current_title = None
            current_priority = None
            buffer = []
            return

        detail = "\n".join(line for line in buffer if line and line != "View Source →").strip()
        full_text = f"{current_title}\n{detail}".strip()
        urls = sorted(set(URL_RE.findall(full_text)))
        dois = sorted(set(match.group(0).rstrip(".,;") for match in DOI_RE.finditer(full_text)))
        destinations = _destinations(current_domain, full_text)
        follow_up = _follow_up_tasks(current_domain, full_text)
        item_id = _fingerprint(sender, message_id, current_domain, current_title, detail)

        items.append(
            {
                "intelligence_id": item_id,
                "lifecycle": "DISCOVERED",
                "knowledge_delta": "UNASSESSED",
                "domain": current_domain,
                "title": current_title,
                "priority": (current_priority or "MEDIUM").upper(),
                "detail": detail,
                "source_urls": urls,
                "dois": dois,
                "verification_required": True,
                "canonical_destinations": destinations,
                "follow_up_tasks": follow_up,
                "automatic_actions_allowed": list(AUTO_INTERNAL_ACTIONS),
                "approval_required_for": list(APPROVAL_REQUIRED_ACTIONS),
                "external_contacted": False,
                "canonical_graph_mutated": False,
                "parser_version": INTELLIGENCE_PARSER_VERSION,
            }
        )
        current_title = None
        current_priority = None
        buffer = []

    for line in lines:
        if line in SECTION_DOMAINS:
            flush()
            current_domain = SECTION_DOMAINS[line]
            continue
        if current_domain is None:
            continue

        priority_match = PRIORITY_RE.search(line)
        if priority_match:
            flush()
            current_priority = priority_match.group(1)
            current_title = PRIORITY_RE.sub("", line).strip()
            continue

        if current_title is not None:
            buffer.append(line)

    flush()
    return items


def intelligence_tasks(items: Iterable[dict[str, object]]) -> list[IntakeTask]:
    """Convert assimilation follow-up steps into the existing review task contract."""
    tasks: list[IntakeTask] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        title = str(item.get("title") or "External intelligence item")
        priority = str(item.get("priority") or "MEDIUM")
        for task_type in item.get("follow_up_tasks", []):
            task_name = str(task_type)
            key = (task_name, title)
            if key in seen:
                continue
            seen.add(key)
            tasks.append(
                IntakeTask(
                    task_type=task_name.lower(),
                    title=f"{task_name.replace('_', ' ').title()}: {title}",
                    priority=priority,
                    rationale=(
                        "External intelligence candidate; perform bounded read-only evaluation before "
                        "canonical promotion or external action."
                    ),
                )
            )
    return tasks


def assimilation_summary(items: list[dict[str, object]]) -> dict[str, object]:
    destinations = sorted(
        {
            str(destination)
            for item in items
            for destination in item.get("canonical_destinations", [])
        }
    )
    task_types = sorted(
        {str(task) for item in items for task in item.get("follow_up_tasks", [])}
    )
    return {
        "parser_version": INTELLIGENCE_PARSER_VERSION,
        "items_discovered": len(items),
        "canonical_destinations": destinations,
        "follow_up_task_types": task_types,
        "external_contacted": False,
        "canonical_graph_mutated": False,
        "publication_performed": False,
    }
