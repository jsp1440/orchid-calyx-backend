"""Featured Genus selection — reproducible rotation with editorial override.

Contract: featured-genus-selection/v1

The deterministic rotation mirrors the frontend `featuredGenus.ts` contract
exactly: a 12-hour UTC window, `floor(epoch / window) % len(candidates)`,
cycling through the curated homepage-safe candidate list. Every visitor and
every service therefore resolves the same genus at the same moment without
any scheduler, database write, or coordination service.

An editorial override is operational input carried in a versioned, reviewed
JSON policy file — not a scientific claim and not a scheduled job. Overrides
must be bounded, canonical genus names with a recorded reviewer, reason, and
expiry; an expired or malformed override is ignored loudly (reported in the
response), never silently applied and never fatal.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.featured_genus import FEATURED_GENUS_SELECTION_CONTRACT

ROTATION_WINDOW_SECONDS = 12 * 60 * 60

CANONICAL_GENUS_RE = re.compile(r"^[A-Z][A-Za-z-]+$")
MAX_GENUS_LENGTH = 120

# Mirrors FEATURED_GENERA in the frontend `src/lib/featuredGenus.ts`. The two
# lists must stay identical so backend selection and frontend identity agree.
DEFAULT_ROTATION_CANDIDATES: tuple[str, ...] = (
    "Cattleya",
    "Dracula",
    "Masdevallia",
    "Dendrobium",
    "Bulbophyllum",
    "Catasetum",
    "Vanilla",
    "Phalaenopsis",
)

DEFAULT_POLICY_PATH = (
    Path(__file__).resolve().parents[2]
    / "runtime"
    / "requirements"
    / "featured_genus_selection_policy.json"
)

OVERRIDE_REQUIRED_FIELDS = ("genus", "reason", "reviewer", "expires_at")


def canonical_genus(value: Any) -> str:
    """Validate a bounded canonical genus token (never a binomial or route)."""
    genus = str(value or "").strip()
    if not genus or len(genus) > MAX_GENUS_LENGTH or not CANONICAL_GENUS_RE.fullmatch(genus):
        raise ValueError("A bounded canonical genus name is required")
    return genus


def load_selection_policy(path: Path | None = None) -> tuple[dict[str, Any], str | None]:
    """Load the editorial selection policy. Missing or malformed policy is a
    reported condition, not a failure: rotation falls back to deterministic."""
    policy_path = path or DEFAULT_POLICY_PATH
    try:
        with policy_path.open("r", encoding="utf-8") as handle:
            policy = json.load(handle)
    except FileNotFoundError:
        return {}, f"selection policy not found at {policy_path}"
    except (OSError, json.JSONDecodeError) as exc:
        return {}, f"selection policy unreadable: {type(exc).__name__}"
    if not isinstance(policy, dict):
        return {}, "selection policy is not a JSON object"
    return policy, None


def _parse_expiry(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        if len(text) == 10:  # YYYY-MM-DD
            return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def evaluate_override(
    raw: Any,
    *,
    candidates: tuple[str, ...],
    now_seconds: int,
) -> dict[str, Any]:
    """Evaluate the editorial override. Returns a status record; never raises."""
    if raw is None:
        return {"status": "none"}
    if not isinstance(raw, dict):
        return {"status": "rejected", "reason": "override is not an object"}

    missing = [field for field in OVERRIDE_REQUIRED_FIELDS if not raw.get(field)]
    if missing:
        return {"status": "rejected", "reason": "missing required fields", "missing": missing}

    try:
        genus = canonical_genus(raw.get("genus"))
    except ValueError:
        return {"status": "rejected", "reason": "override genus is not a bounded canonical genus"}

    expires_at = _parse_expiry(raw.get("expires_at"))
    if expires_at is None:
        return {"status": "rejected", "reason": "expires_at is not a parseable ISO-8601 date", "genus": genus}
    if expires_at.timestamp() <= now_seconds:
        return {
            "status": "expired",
            "genus": genus,
            "expires_at": raw.get("expires_at"),
            "reviewer": raw.get("reviewer"),
        }

    # Genera outside the curated rotation need an explicit evidence review
    # flag so the homepage never repeatedly features genera with insufficient
    # usable evidence on editorial whim alone.
    if genus not in candidates and raw.get("evidence_reviewed") is not True:
        return {
            "status": "rejected",
            "reason": "non-candidate genus requires evidence_reviewed: true",
            "genus": genus,
        }

    return {
        "status": "active",
        "genus": genus,
        "reason": str(raw.get("reason")).strip(),
        "reviewer": str(raw.get("reviewer")).strip(),
        "expires_at": raw.get("expires_at"),
        "evidence_reviewed": raw.get("evidence_reviewed") is True,
    }


def select_featured_genus(
    now_seconds: int | None = None,
    *,
    policy: dict[str, Any] | None = None,
    policy_path: Path | None = None,
) -> dict[str, Any]:
    """Resolve the current Featured Genus selection.

    Pure and deterministic given the same inputs: same epoch in, same
    selection out. This function never schedules anything and never writes.
    """
    now = int(time.time() if now_seconds is None else now_seconds)

    load_error = None
    if policy is None:
        policy, load_error = load_selection_policy(policy_path)

    rotation = policy.get("rotation") if isinstance(policy.get("rotation"), dict) else {}
    raw_candidates = rotation.get("candidates")
    candidates = DEFAULT_ROTATION_CANDIDATES
    candidates_note = None
    if isinstance(raw_candidates, list) and raw_candidates:
        try:
            candidates = tuple(canonical_genus(item) for item in raw_candidates)
        except ValueError:
            candidates_note = "policy rotation candidates contain a non-canonical genus; using defaults"

    window_seconds = rotation.get("window_seconds")
    if not isinstance(window_seconds, int) or window_seconds <= 0:
        window_seconds = ROTATION_WINDOW_SECONDS

    window_index = (now // window_seconds) % len(candidates)
    deterministic = candidates[window_index]
    window_started = (now // window_seconds) * window_seconds

    override = evaluate_override(
        policy.get("override"),
        candidates=candidates,
        now_seconds=now,
    )
    override_active = override.get("status") == "active"

    result: dict[str, Any] = {
        "contract": FEATURED_GENUS_SELECTION_CONTRACT,
        "genus": override["genus"] if override_active else deterministic,
        "source": "editorial_override" if override_active else "deterministic_rotation",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {
            "index": window_index,
            "window_seconds": window_seconds,
            "started_at": datetime.fromtimestamp(window_started, tz=timezone.utc).isoformat(),
            "ends_at": datetime.fromtimestamp(window_started + window_seconds, tz=timezone.utc).isoformat(),
            "seconds_remaining": window_seconds - (now % window_seconds),
        },
        "rotation": {
            "window_seconds": window_seconds,
            "candidates": list(candidates),
            "deterministic_genus": deterministic,
        },
        "override": override,
        "selection_caution": (
            "The featured genus is a navigational and editorial identity, not "
            "scientific evidence. Consumers must fetch canonical evidence for "
            "it through the governed read contracts."
        ),
    }
    if load_error:
        result["policy_load_warning"] = load_error
    if candidates_note:
        result["candidates_warning"] = candidates_note
    return result
