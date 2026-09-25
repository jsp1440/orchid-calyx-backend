"""Detect frontend/backend API contract drift, and turn it into bounded work.

Three real Release 1 defects were found by hand this way: two Mission Control
panels whose backend producer had never been written, and a signup form
posting to a relative path that resolved to the SPA shell and discarded every
address it collected. All three were invisible to both repositories' test
suites, because each side was internally consistent and only the seam between
them was wrong.

This module makes that check repeatable, so the autonomous engine can find the
next one instead of waiting for someone to look.

Two kinds of drift
------------------
``missing_producer``
    The frontend calls a path the backend does not serve. The consumer is
    usually complete and typed; there is simply nothing on the other end.

``relative_origin``
    A call whose URL literal is relative. Orchid Continuum is served from
    Render, whose ``public/_redirects`` rewrites every unmatched path to
    ``/index.html`` with status 200. A relative API call therefore resolves
    successfully, with HTML, and reads as a working response. This is the
    worst class of the three, because it fails silently in production.

Bounded by construction
-----------------------
An improvement loop that emits unlimited work is a nuisance, not a capability.
Findings are deduplicated by path, capped, and ranked, and only paths
attributed to this backend can become work. A call aimed at the separate
public API is reported for visibility but never queued here, because this
repository cannot fix it.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA = "oc.api-contract-drift.v1"

# Defaults chosen so one pass can never flood the queue.
DEFAULT_MAX_WORK_ITEMS = 10
DEFAULT_ISSUE_BASE = 90_000

#: Drift kinds, worst first. Order is the ranking.
DRIFT_KINDS: tuple[str, ...] = ("relative_origin", "missing_producer")

_SEVERITY = {
    # Silent success in production. Nothing surfaces the failure.
    "relative_origin": "high",
    # A dead panel. Visible, and usually fails closed.
    "missing_producer": "medium",
}

#: Which backend a call is aimed at. Only CALYX is actionable here.
TARGET_CALYX = "calyx"
TARGET_PUBLIC_API = "public-api"
TARGET_UNKNOWN = "unknown"

# Matches an /api path inside a string literal, including the common
# `${BASE}/api/x` form where the origin is interpolated in front of it.
_API_LITERAL = re.compile(r"""[`'"](?:\$\{[^}]*\})?(/api/[A-Za-z0-9_\-/{}$.:()]+)""")
_TEMPLATE_HOLE = re.compile(r"\$\{[^}]*\}")
_COLON_PARAM = re.compile(r":[A-Za-z0-9_]+")
_ROUTE_PARAM = re.compile(r"\{[^}]+\}")
#: Readable stand-in for a caller-supplied path segment, so a reported path
#: is legible in a work item rather than carrying a control character.
PARAM_SENTINEL = "{*}"
#: Marks a literal whose full path could not be read. Never becomes a finding.
UNPARSED = "<unparsed>"
# A fetch whose first argument is a relative /api literal.
_RELATIVE_FETCH = re.compile(r"""fetch\(\s*[`'"]/api/""")


_BLOCK_COMMENT = re.compile(r"/\*[\s\S]*?\*/")
_LINE_COMMENT = re.compile(r"^[ \t]*//.*$", re.MULTILINE)


def strip_comments(text: str) -> str:
    """Blank out comments, preserving offsets so line numbers stay correct.

    A path named in a docstring is documentation, not a call. Scanning it
    produces a finding nobody can act on, and an improvement loop that emits
    work for its own comments is the definition of busywork.
    """

    def blank(match: re.Match[str]) -> str:
        return "".join("\n" if ch == "\n" else " " for ch in match.group(0))

    return _LINE_COMMENT.sub(blank, _BLOCK_COMMENT.sub(blank, text))


@dataclass(frozen=True, slots=True)
class ApiCallSite:
    """One place the frontend names an API path."""

    raw_path: str
    file: str
    line: int
    target: str
    relative: bool

    @property
    def normalized(self) -> str:
        return normalize_call_path(self.raw_path)


@dataclass(frozen=True, slots=True)
class DriftFinding:
    """One contract defect, with every place it appears."""

    kind: str
    path: str
    target: str
    detail: str
    call_sites: tuple[ApiCallSite, ...] = field(default=())

    @property
    def severity(self) -> str:
        return _SEVERITY.get(self.kind, "low")

    @property
    def actionable_here(self) -> bool:
        """Can this repository fix it?

        A missing producer for the separate public API is real, but it cannot
        be fixed from this codebase, so queueing it would manufacture work
        nobody here can complete.
        """
        if self.kind == "relative_origin":
            return True
        return self.target == TARGET_CALYX

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "path": self.path,
            "target": self.target,
            "severity": self.severity,
            "detail": self.detail,
            "actionable_here": self.actionable_here,
            "call_sites": [
                {"file": site.file, "line": site.line, "raw_path": site.raw_path}
                for site in self.call_sites
            ],
        }


# ---------------------------------------------------------------------------
# Normalization and matching
# ---------------------------------------------------------------------------


def normalize_call_path(raw: str) -> str:
    """Reduce a call literal to a comparable path.

    Template holes and ``:param`` segments both become a single wildcard
    segment, so ``/api/intake/${id}/approve`` and ``/api/intake/:id/approve``
    compare equal to the route ``/api/intake/{source_id}/approve``.
    """
    path = _TEMPLATE_HOLE.sub(PARAM_SENTINEL, raw)
    # A hole containing a call, like ${encodeURIComponent(name)}, is cut off
    # by the literal character class before its closing brace. What survives
    # is a fragment, not a path, so everything from the opening ${ becomes one
    # parameter segment rather than being compared literally.
    if "${" in path:
        # The literal was cut off inside a template hole, so the rest of the
        # path is unknown. Reporting a guess here produced false findings for
        # endpoints that exist; an unreadable path is marked and excluded
        # instead. A missed defect is recoverable, a fabricated one trains
        # people to ignore the detector.
        return UNPARSED
    path = _COLON_PARAM.sub(PARAM_SENTINEL, path)
    path = path.split("?", 1)[0].rstrip("/")
    # A hole glued straight onto the prefix, as in `/api/thing${path}`, is a
    # base URL a helper appends to, not a path. The real calls live at the
    # helper's call sites and are scanned there, so reporting the prefix
    # would invent a defect for an endpoint nobody requests.
    if PARAM_SENTINEL in path and f"/{PARAM_SENTINEL}" not in path:
        return UNPARSED
    return path or "/"


def build_route_matchers(routes: list[str]) -> list[str]:
    """Kept for callers that pre-build a matcher set.

    Matching is segment-wise now, so the routes need no compilation; this
    returns them unchanged rather than breaking the call sites.
    """
    return list(routes)


def _segments(path: str) -> list[str]:
    return [seg for seg in path.strip("/").split("/") if seg != ""]


def _is_wildcard(segment: str) -> bool:
    return segment == PARAM_SENTINEL or (
        segment.startswith("{") and segment.endswith("}")
    )


def path_is_served(normalized: str, routes: list[str]) -> bool:
    """Does any backend route serve this normalized call path?

    Comparison is segment-wise and symmetric: a segment matches when the two
    sides are equal, or when either side is a parameter. Either side, because
    a caller-supplied segment can just as well be a literal route segment at
    runtime -- ``/api/lexicon/${which}`` really can resolve to
    ``/api/lexicon/search``. Treating that as missing would queue work for an
    endpoint that exists, and a false finding in an autonomous loop is worse
    than a missed one.
    """
    call = _segments(normalized)
    for route in routes:
        if ":path}" in route:
            # A path converter swallows the rest, so only the prefix matters.
            prefix = _segments(route.split("{", 1)[0])
            if call[: len(prefix)] == prefix:
                return True
            continue
        target = _segments(route)
        if len(target) != len(call):
            continue
        if all(
            a == b or _is_wildcard(a) or _is_wildcard(b) for a, b in zip(call, target)
        ):
            return True
    return False


# ---------------------------------------------------------------------------
# Scanning a frontend source tree
# ---------------------------------------------------------------------------


def classify_target(text: str, offset: int) -> tuple[str, bool]:
    """Decide which backend a call is aimed at, and whether it is relative.

    Looks at the code immediately preceding the literal, which is where the
    base origin is concatenated, then falls back to what the module imports.
    """
    window = text[max(0, offset - 400) : offset]
    if "CALYX_BACKEND_BASE_URL" in window:
        return TARGET_CALYX, False
    if "BACKEND_BASE_URL" in window or "API_BASE_URL" in window:
        return TARGET_PUBLIC_API, False

    relative = bool(_RELATIVE_FETCH.search(text[max(0, offset - 16) : offset + 8]))
    if "CALYX_BACKEND_BASE_URL" in text:
        return TARGET_CALYX, relative
    if "apiRequest" in text or "API_BASE_URL" in text:
        return TARGET_PUBLIC_API, relative
    return TARGET_UNKNOWN, relative


def scan_frontend_calls(src_root: str | Path) -> list[ApiCallSite]:
    """Collect every API path literal in a frontend source tree."""
    root = Path(src_root)
    sites: list[ApiCallSite] = []
    for file in sorted(root.rglob("*.ts*")):
        name = file.name
        if ".test." in name or ".spec." in name or ".d.ts" in name:
            continue
        try:
            text = file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        text = strip_comments(text)
        for match in _API_LITERAL.finditer(text):
            target, relative = classify_target(text, match.start())
            sites.append(
                ApiCallSite(
                    raw_path=match.group(1),
                    file=str(file),
                    line=text.count("\n", 0, match.start()) + 1,
                    target=target,
                    relative=relative,
                )
            )
    return sites


def find_relative_fetches(src_root: str | Path) -> list[ApiCallSite]:
    """Find fetch calls whose first argument is a literal relative API path."""
    root = Path(src_root)
    sites: list[ApiCallSite] = []
    for file in sorted(root.rglob("*.ts*")):
        if ".test." in file.name or ".spec." in file.name:
            continue
        try:
            text = file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        text = strip_comments(text)
        for match in _RELATIVE_FETCH.finditer(text):
            literal = _API_LITERAL.search(text, match.start())
            raw = literal.group(1) if literal else "/api/"
            sites.append(
                ApiCallSite(
                    raw_path=raw,
                    file=str(file),
                    line=text.count("\n", 0, match.start()) + 1,
                    target=TARGET_UNKNOWN,
                    relative=True,
                )
            )
    return sites


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def detect_drift(
    call_sites: list[ApiCallSite],
    backend_routes: list[str],
    *,
    relative_sites: list[ApiCallSite] | None = None,
) -> list[DriftFinding]:
    """Compare declared calls against served routes. Pure and deterministic."""
    matchers = build_route_matchers(backend_routes)
    findings: dict[tuple[str, str], DriftFinding] = {}

    for site in relative_sites or []:
        key = ("relative_origin", site.raw_path)
        existing = findings.get(key)
        sites = (*(existing.call_sites if existing else ()), site)
        findings[key] = DriftFinding(
            kind="relative_origin",
            path=site.raw_path,
            target=site.target,
            detail=(
                "fetch() is called with a relative API path. Render rewrites "
                "every unmatched path to /index.html with status 200, so this "
                "resolves to the app shell and reads as a successful response."
            ),
            call_sites=sites,
        )

    for site in call_sites:
        if site.normalized == UNPARSED:
            continue
        if path_is_served(site.normalized, matchers):
            continue
        key = ("missing_producer", site.normalized)
        existing = findings.get(key)
        sites = (*(existing.call_sites if existing else ()), site)
        findings[key] = DriftFinding(
            kind="missing_producer",
            path=site.normalized,
            target=site.target,
            detail=("The frontend calls this path and no backend route serves it."),
            call_sites=sites,
        )

    return sorted(
        findings.values(),
        key=lambda f: (DRIFT_KINDS.index(f.kind), not f.actionable_here, f.path),
    )


# ---------------------------------------------------------------------------
# Turning findings into bounded work
# ---------------------------------------------------------------------------


def stable_identity(path: str, *, span: int = 9_000) -> int:
    """A deterministic identifier for a defect path.

    Python's built-in hash is salted per process, so it would give the same
    defect a different work-item identity on every run and defeat the
    engine's deduplication entirely. A digest is stable across processes and
    across machines, which is what makes "report each defect once" true.
    """
    digest = hashlib.sha256(path.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % span


def findings_to_work_items(
    findings: list[DriftFinding],
    *,
    limit: int = DEFAULT_MAX_WORK_ITEMS,
    issue_base: int = DEFAULT_ISSUE_BASE,
) -> list[dict[str, Any]]:
    """Convert actionable findings into work items the engine can admit.

    Only findings this repository can act on become work, and the list is
    capped. The identifier is derived from the path, so the same defect
    produces the same work item on every pass and the engine's existing
    deduplication suppresses it rather than re-queueing it forever.
    """
    items: list[dict[str, Any]] = []
    for finding in findings:
        if len(items) >= limit:
            break
        if not finding.actionable_here:
            continue
        items.append(
            {
                "number": issue_base + stable_identity(finding.path),
                "title": f"contract drift ({finding.kind}): {finding.path}",
                "repo": "orchid-calyx-backend",
                "priority": 0 if finding.severity == "high" else 1,
                "consequence_risk": "low",
            }
        )
    return items


@dataclass
class ContractDriftWorkSource:
    """A WorkSource that emits real integration defects, once each.

    Satisfies the protocol in ``runtime.autonomy_cycle_engine``. It reports
    its findings on the first cycle and nothing afterwards, because the
    defects are a snapshot rather than a stream; re-reporting them every cycle
    would be exactly the unbounded issue generation this design forbids.
    """

    findings: list[DriftFinding]
    name: str = "api-contract-drift"
    limit: int = DEFAULT_MAX_WORK_ITEMS
    _served: bool = False

    def discover(self, cycle: int) -> list[Any]:
        if self._served:
            return []
        self._served = True
        return findings_to_work_items(self.findings, limit=self.limit)


def build_report(findings: list[DriftFinding], *, unparsed: int = 0) -> dict[str, Any]:
    actionable = [f for f in findings if f.actionable_here]
    return {
        "schema": SCHEMA,
        "total_findings": len(findings),
        # Literals whose full path could not be read, and so were excluded
        # rather than guessed at.
        "unparsed_call_sites": unparsed,
        "actionable_here": len(actionable),
        "by_kind": {
            kind: sum(1 for f in findings if f.kind == kind) for kind in DRIFT_KINDS
        },
        "findings": [f.as_dict() for f in findings],
    }


def load_routes(path: str | Path) -> list[str]:
    """Read a backend route table from JSON.

    Accepts a list of paths, or the ``[[path, methods], ...]`` shape produced
    by enumerating a FastAPI application.
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    routes: list[str] = []
    for entry in raw:
        if isinstance(entry, str):
            routes.append(entry)
        elif isinstance(entry, (list, tuple)) and entry and isinstance(entry[0], str):
            routes.append(entry[0])
    return routes
