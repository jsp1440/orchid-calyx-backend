"""Durable completion-receipt tracker for the Orchid Continuous Engine.

Wraps `gh issue comment` with:
  - TRACKER_EXHAUSTED classification (GitHub 2500-comment ceiling)
  - Auto-rotation to a successor tracker issue
  - Idempotent successor creation (concurrent-safe via check-before-create)
  - Fail-closed on auth/permission/security errors
  - GitHub-native persistence — reconstructable from GitHub state alone
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys

TRACKER_SUCCESSOR_TAG = "OC-TRACKER-SUCCESSOR-V1"
TRACKER_ACTIVE_LABEL = "oc-active-tracker"
TRACKER_BASE_LABEL = "oc-tracker"

_EXHAUSTED_SIGNALS = ("2500", "Commenting is disabled", "addComment")
_AUTH_SIGNALS = (
    "HTTP 401",
    "HTTP 403",
    "authentication",
    "Resource not accessible",
    "Permission denied",
    "forbidden",
    "Must have",
    "requires authentication",
)


class TrackerError(Exception):
    """Unrecoverable tracker failure — step exits 1."""


class TrackerExhausted(TrackerError):
    """GitHub 2500-comment ceiling hit; rotate to successor."""


class TrackerAuthError(TrackerError):
    """Auth/permission/security error — fail closed, do not rotate."""


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------


def _classify_error(stderr: str) -> type[TrackerError] | None:
    """Return the TrackerError subclass for a gh-command failure, or None."""
    lower = stderr.lower()
    if any(s.lower() in lower for s in _EXHAUSTED_SIGNALS):
        return TrackerExhausted
    if any(s.lower() in lower for s in _AUTH_SIGNALS):
        return TrackerAuthError
    return None


# ---------------------------------------------------------------------------
# Successor record serialization (HTML comment, same pattern as checker_dispatch)
# ---------------------------------------------------------------------------


def _serialize_successor(exhausted_issue: int, successor_issue: int) -> str:
    payload = json.dumps(
        {
            "tag": TRACKER_SUCCESSOR_TAG,
            "exhausted_issue": exhausted_issue,
            "successor_issue": successor_issue,
        },
        sort_keys=True,
        indent=2,
    )
    return (
        f"<!-- {TRACKER_SUCCESSOR_TAG}\n{payload}\n-->\n"
        f"[OC-TRACKER] Issue #{exhausted_issue} reached GitHub's 2500-comment ceiling. "
        f"Successor tracker: #{successor_issue}. "
        f"Continuity preserved via `{TRACKER_SUCCESSOR_TAG}` record."
    )


def _parse_successor_comment(body: str) -> int | None:
    """Extract successor issue number from an OC-TRACKER-SUCCESSOR-V1 comment body."""
    tag = TRACKER_SUCCESSOR_TAG
    start = body.find(f"<!-- {tag}")
    if start == -1:
        return None
    end = body.find("-->", start)
    if end == -1:
        return None
    json_text = body[start + len(f"<!-- {tag}") : end].strip()
    try:
        payload = json.loads(json_text)
        return int(payload["successor_issue"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Default gh runner
# ---------------------------------------------------------------------------


def _default_run(*args: str) -> tuple[int, str, str]:
    result = subprocess.run(["gh", *args], capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def find_active_tracker(
    repo: str,
    configured_tracker: int,
    *,
    _run=None,
) -> int:
    """Return the issue number of the currently active tracker.

    Queries the `oc-active-tracker` label to find any rotated successor.
    Falls back to `configured_tracker` when no labelled successor exists.
    Raises TrackerAuthError on permission failures.
    """
    run = _run or _default_run

    rc, out, err = run(
        "issue",
        "list",
        "--repo",
        repo,
        "--label",
        TRACKER_ACTIVE_LABEL,
        "--state",
        "open",
        "--limit",
        "5",
        "--json",
        "number",
    )
    if rc != 0:
        exc_cls = _classify_error(err) or TrackerError
        raise exc_cls(f"Cannot list active trackers: {err.strip()}")

    try:
        items = json.loads(out or "[]")
        if items:
            return int(items[0]["number"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        pass

    return configured_tracker


def _find_existing_successor(
    repo: str,
    exhausted_issue: int,
    *,
    _run=None,
) -> int | None:
    """Return successor issue number if exhausted_issue already has a successor record.

    Returns None on any error or when no successor exists.
    """
    run = _run or _default_run

    rc, out, err = run(
        "api",
        "--paginate",
        f"repos/{repo}/issues/{exhausted_issue}/comments?per_page=100",
        "--jq",
        f'.[] | select(.body | test("{TRACKER_SUCCESSOR_TAG}")) | .body',
    )
    if rc != 0 or not out.strip():
        return None

    for raw_line in out.splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        # jq may output the string JSON-encoded (with surrounding quotes) or raw
        body = raw_line
        try:
            decoded = json.loads(raw_line)
            if isinstance(decoded, str):
                body = decoded
        except (json.JSONDecodeError, ValueError):
            pass
        result = _parse_successor_comment(body)
        if result is not None:
            return result

    return None


def _create_successor_issue(
    repo: str,
    exhausted_issue: int,
    *,
    _run=None,
) -> int:
    """Create a new tracker issue as successor. Returns its issue number."""
    run = _run or _default_run

    title = (
        f"[OC-TRACKER-SUCCESSOR] Continuous completion tracker "
        f"(rotated from #{exhausted_issue})"
    )
    body = (
        f"Successor to tracker issue #{exhausted_issue}, which reached GitHub's "
        f"2500-comment ceiling. Created automatically by `oc_tracker.py`.\n\n"
        f"Predecessor: #{exhausted_issue}"
    )

    rc, out, err = run(
        "issue",
        "create",
        "--repo",
        repo,
        "--title",
        title,
        "--body",
        body,
        "--label",
        TRACKER_BASE_LABEL,
        "--label",
        TRACKER_ACTIVE_LABEL,
        "--json",
        "number",
    )
    if rc != 0:
        exc_cls = _classify_error(err) or TrackerError
        raise exc_cls(f"Failed to create successor tracker issue: {err.strip()}")

    try:
        return int(json.loads(out)["number"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise TrackerError(
            f"Unexpected response creating successor issue: {out!r}"
        ) from exc


def _rotate_tracker(
    repo: str,
    exhausted_issue: int,
    *,
    _run=None,
) -> int:
    """Create or reuse a successor for exhausted_issue. Returns successor issue number.

    Idempotent: if a successor record already exists on the exhausted issue
    (placed by a concurrent or prior run), returns it without creating a new one.
    """
    run = _run or _default_run

    # Check for an existing successor before creating one (concurrent-safe pre-check)
    existing = _find_existing_successor(repo, exhausted_issue, _run=run)
    if existing is not None:
        return existing

    # No existing successor — create one
    successor = _create_successor_issue(repo, exhausted_issue, _run=run)

    # Post the durable successor record on the old issue so future runs follow the chain.
    # If the old issue is still exhausted (or the write fails for non-auth reasons),
    # label-based discovery via oc-active-tracker still works — best-effort.
    successor_body = _serialize_successor(exhausted_issue, successor)
    rc, _, err = run(
        "issue",
        "comment",
        str(exhausted_issue),
        "--repo",
        repo,
        "--body",
        successor_body,
    )
    if rc != 0:
        exc_cls = _classify_error(err)
        if exc_cls is TrackerAuthError:
            raise TrackerAuthError(
                f"Cannot post successor record on #{exhausted_issue}: {err.strip()}"
            )
        # TRACKER_EXHAUSTED or unknown: label-based fallback is sufficient — continue

    return successor


def post_tracker_comment(
    repo: str,
    configured_tracker: int,
    body: str,
    *,
    _run=None,
) -> int:
    """Post body to the active tracker. Returns the issue number posted to.

    If the active tracker is exhausted, auto-rotates to a durable successor.
    Raises TrackerAuthError on permission/auth/security failures (fail closed).
    Raises TrackerError on other unrecoverable failures.
    """
    run = _run or _default_run

    active = find_active_tracker(repo, configured_tracker, _run=run)

    rc, _, err = run(
        "issue",
        "comment",
        str(active),
        "--repo",
        repo,
        "--body",
        body,
    )
    if rc == 0:
        return active

    exc_cls = _classify_error(err)

    if exc_cls is TrackerAuthError:
        raise TrackerAuthError(f"Auth error posting to tracker #{active}: {err.strip()}")

    if exc_cls is TrackerExhausted:
        successor = _rotate_tracker(repo, active, _run=run)

        rc2, _, err2 = run(
            "issue",
            "comment",
            str(successor),
            "--repo",
            repo,
            "--body",
            body,
        )
        if rc2 != 0:
            exc_cls2 = _classify_error(err2)
            if exc_cls2 is TrackerAuthError:
                raise TrackerAuthError(
                    f"Auth error posting to successor #{successor}: {err2.strip()}"
                )
            raise TrackerError(
                f"Failed to post to successor #{successor}: {err2.strip()}"
            )

        return successor

    # Unknown gh error — fail closed
    raise TrackerError(f"Unexpected error posting to tracker #{active}: {err.strip()}")


# ---------------------------------------------------------------------------
# CLI entry point (called from workflow bash step)
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Post a durable comment to the OC continuous-completion tracker."
    )
    parser.add_argument("--repo", required=True, help="owner/repo")
    parser.add_argument(
        "--tracker",
        type=int,
        required=True,
        help="Configured RUNTIME_TRACKER_ISSUE number",
    )
    parser.add_argument("--body", required=True, help="Comment body to post")
    args = parser.parse_args()

    try:
        posted_to = post_tracker_comment(args.repo, args.tracker, args.body)
        print(f"[OC-TRACKER] Comment posted to issue #{posted_to}.")
    except TrackerAuthError as exc:
        print(f"[OC-TRACKER] AUTH/SECURITY ERROR (fail closed): {exc}", file=sys.stderr)
        sys.exit(1)
    except TrackerExhausted as exc:
        print(f"[OC-TRACKER] TRACKER_EXHAUSTED: {exc}", file=sys.stderr)
        sys.exit(1)
    except TrackerError as exc:
        print(f"[OC-TRACKER] TRACKER ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
