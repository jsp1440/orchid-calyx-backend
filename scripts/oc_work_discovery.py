"""Find real Orchid Continuum work in the repository, without inventing any.

The controller has been able to execute a queue for a while. What it has not
been able to do is fill one: every TaskLeaf so far arrived because a person
wrote an issue and attached a label. The live plan step says so in its own
words, every five minutes — eight free lanes, nothing admitted — and a factory
whose intake is a human is not a factory.

This module is the intake. It reads the repository and emits bounded candidate
tasks, each carrying the evidence that justifies it. Two rules make that safe:

**Every candidate names a fact, not a judgement.** A missing dependency is the
difference between two checked-in files. A failing test is a node id a runner
produced. Neither is a reading of prose, and neither can be produced by a model
that has decided something would be nice to build.

**A candidate the evidence does not place is reported unplaced.** Lane binding
comes from ``oc_product_lanes``, a path table. When a path matches nothing, the
candidate keeps ``lane=None`` and is emitted as an analysis task that asks for
the binding — it never receives the closest-looking lane. That is the same rule
the frontend's graph binding follows, and it exists because the cheapest way to
corrupt a portfolio is to let a discoverer guess.

Nothing here mutates GitHub, calls a provider, or spends anything. It returns a
report; ``oc_work_materialize`` decides what to do with it.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, packages_distributions
from importlib.metadata import version as _distribution_version
from pathlib import Path
from typing import Any

from scripts.oc_product_lanes import (
    LOWEST_PRIORITY,
    ProductLane,
    lane_for_path,
    rank_of,
)
from scripts.oc_validation_commands import VALIDATION_COMMANDS

REPORT_SCHEMA = "oc.work-discovery.v1"

#: Sources whose remedy is a single line the evidence fully determines: the
#: distribution is named by the evidence, the file is fixed by the source, and
#: the version is read from the environment. Anything else needs authoring.
MECHANICAL_SOURCES: dict[str, str] = {
    "dependency-gap": "requirements-dev.txt",
    "undeclared-import": "requirements.txt",
}


def installed_version(distribution: str) -> str | None:
    """The version of ``distribution`` installed here, or None. Asked, not guessed."""
    try:
        return str(_distribution_version(distribution))
    except PackageNotFoundError:
        return None


def declare_remedy(source: str, distribution: str, *, version_of=installed_version) -> dict[str, Any]:
    """The structured remedy an edit lane can apply without reading prose.

    ``installed_version`` is the environment's answer at discovery time and may
    be None; the lane asks again in its own environment and refuses to write a
    pin it did not observe.
    """
    return {
        "kind": "declare-distribution",
        "distribution": distribution,
        "requirements_file": MECHANICAL_SOURCES[source],
        "installed_version": version_of(distribution),
    }

#: Pytest markers whose behaviour is supplied by a separate distribution, and
#: the distribution that supplies it. Deliberately a short, explicit table: an
#: unlisted marker yields no candidate, because "this marker probably comes from
#: a plugin named after it" is exactly the kind of guess this module refuses.
MARKER_DISTRIBUTIONS: dict[str, str] = {
    "asyncio": "pytest-asyncio",
    "trio": "pytest-trio",
    "benchmark": "pytest-benchmark",
    "freeze_time": "pytest-freezegun",
}

def markers_used(source: str) -> set[str]:
    """Pytest markers a module actually decorates something with.

    Parsed rather than matched. A regex over the text reports any file that
    merely *mentions* the decorator — this module's own test file holds
    ``@pytest.mark.asyncio`` inside a fixture string, and the first version of
    this function filed it as a ninth affected file. A discoverer that cannot
    tell code from a string about code is not reading evidence.

    A file that does not parse yields nothing: a syntax error is a different
    defect, and reading it as a missing dependency would name the wrong one.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return set()

    def marker_of(node: ast.AST) -> str | None:
        # pytest.mark.NAME, and pytest.mark.NAME(...) for a parametrised marker.
        if isinstance(node, ast.Call):
            node = node.func
        if not isinstance(node, ast.Attribute):
            return None
        parent = node.value
        if not isinstance(parent, ast.Attribute) or parent.attr != "mark":
            return None
        root = parent.value
        if isinstance(root, ast.Name) and root.id == "pytest":
            return node.attr
        return None

    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for decorator in node.decorator_list:
                name = marker_of(decorator)
                if name:
                    names.add(name)
        # `pytestmark = pytest.mark.asyncio` applies to a whole module.
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "pytestmark" for target in node.targets
        ):
            values = node.value.elts if isinstance(node.value, (ast.List, ast.Tuple)) else [node.value]
            for value in values:
                name = marker_of(value)
                if name:
                    names.add(name)
    return names

#: A requirement line's distribution name, ignoring extras, markers and pins.
REQUIREMENT_NAME = re.compile(r"^\s*(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)")

#: Where a registered custom mark would be declared. A marker registered by this
#: repository is this repository's own, and is not a missing dependency.
MARKER_REGISTRIES = ("pytest.ini", "setup.cfg", "tox.ini", "pyproject.toml")

#: pytest's own summary lines.
PYTEST_OUTCOME = re.compile(
    r"^(?P<outcome>FAILED|ERROR)\s+(?P<nodeid>\S+?)(?:\s+-\s+.*)?$", re.MULTILINE
)
PYTEST_SUMMARY = re.compile(
    r"^=+ .*\b(?:passed|failed|error|no tests ran)\b.*=+$|"
    r"^\d+ (?:passed|failed|error)", re.MULTILINE
)


@dataclass(frozen=True)
class Evidence:
    """One checkable fact. ``where`` is a repository path or a pytest node id."""

    kind: str
    where: str
    detail: str

    def to_record(self) -> dict[str, Any]:
        return {"kind": self.kind, "where": self.where, "detail": self.detail}


@dataclass(frozen=True)
class Candidate:
    """One bounded task the repository's own state justifies."""

    source: str
    title: str
    summary: str
    lane: ProductLane | None
    evidence: tuple[Evidence, ...]
    #: Identity of the *condition*, not of this run. Two discovery passes over
    #: an unchanged repository produce the same fingerprint, which is what stops
    #: the queue filling with duplicates of one defect.
    semantic_key: str
    #: Set when the fix is mechanically derivable from the evidence. Recorded so
    #: a reviewer sees what the discoverer believes, never executed from here.
    proposed_remedy: str = ""
    #: True when the candidate exists to *establish* a binding rather than to do
    #: the work. Never carries a lane label.
    analysis_only: bool = False
    #: Structured form of ``proposed_remedy`` for the mechanical sources: the
    #: exact distribution, file and observed version. Empty for every other
    #: source, which is what stops an edit lane from acting on prose.
    remedy: dict[str, Any] = field(default_factory=dict)
    capabilities: tuple[str, ...] = field(default_factory=tuple)
    #: A registered validation command that covers every affected path, when one
    #: exists. This is what makes a filed task executable rather than merely
    #: filed: the deterministic lane admits a task only when it names an
    #: executor that exists, and naming one whose argv does not cover the
    #: evidence would be the same fabrication in a different place.
    validation_command: str = ""

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.semantic_key.encode("utf-8")).hexdigest()[:16]

    @property
    def priority_label(self) -> str:
        if self.lane is None:
            return f"oc-p{LOWEST_PRIORITY}"
        return self.lane.priority_label

    @property
    def labels(self) -> list[str]:
        labels = ["oc-queued", self.priority_label, "oc-discovered"]
        if self.lane is not None:
            labels.append(self.lane.lane_label)
        return labels

    def to_record(self) -> dict[str, Any]:
        return {
            "schema": "oc.work-candidate.v1",
            "source": self.source,
            "title": self.title,
            "summary": self.summary,
            "lane": self.lane.key if self.lane else None,
            "lane_name": self.lane.name if self.lane else None,
            "rank": rank_of(self.lane),
            "analysis_only": self.analysis_only,
            "fingerprint": self.fingerprint,
            "semantic_key": self.semantic_key,
            "proposed_remedy": self.proposed_remedy,
            "remedy": dict(self.remedy),
            "capabilities": list(self.capabilities),
            "validation_command": self.validation_command,
            "labels": self.labels,
            "evidence": [item.to_record() for item in self.evidence],
        }


def covering_validation_command(paths: list[str]) -> str:
    """A registered command whose argv covers every one of ``paths``, or "".

    Coverage is literal containment of each path in the command's argument
    vector. A command that runs *some* of the affected files would settle the
    task on partial evidence, which is the shape of a false pass, so a partial
    match returns nothing at all. The smallest covering command wins: running
    the whole suite would also "cover" them and prove far less about the task.
    """
    if not paths:
        return ""
    best: tuple[int, str] | None = None
    for command_id, command in VALIDATION_COMMANDS.items():
        argv = set(command.argv)
        if all(path in argv for path in paths):
            size = len(command.argv)
            if best is None or size < best[0] or (size == best[0] and command_id < best[1]):
                best = (size, command_id)
    return best[1] if best else ""


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def declared_distributions(root: Path) -> set[str]:
    """Every distribution any requirements file in the repository declares."""
    names: set[str] = set()
    for requirement_file in sorted(root.glob("requirements*.txt")):
        for line in _read(requirement_file).splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(("#", "-")):
                continue
            match = REQUIREMENT_NAME.match(stripped)
            if match:
                names.add(match.group("name").lower().replace("_", "-"))
    return names


def registered_markers(root: Path) -> set[str]:
    """Markers this repository registers for itself.

    A registered marker is repository vocabulary. Reporting it as a missing
    dependency would be a discoverer inventing work out of a naming collision.
    """
    names: set[str] = set()
    for candidate in MARKER_REGISTRIES:
        text = _read(root / candidate)
        if not text or "markers" not in text:
            continue
        for line in text.splitlines():
            stripped = line.strip().strip('"').strip("'").lstrip("-").strip()
            marker = stripped.split(":", 1)[0].split("(", 1)[0].strip()
            if marker and re.fullmatch(r"[a-z_][a-z0-9_]*", marker):
                names.add(marker)
    return names


def discover_dependency_gaps(root: Path) -> list[Candidate]:
    """Tests that use a plugin marker the repository never declares.

    This is not a style finding. Without the distribution, pytest does not run
    the test body at all — it reports the test as failed with "async def
    functions are not natively supported", and the assertions inside never
    execute. So every capability those files are meant to certify is
    *unverified* while looking like an ordinary red test, which is the one
    outcome ``AGENT-OPERATING-MEMORY`` singles out: an absent result and a
    passing result are the same shape on the way out.
    """
    declared = declared_distributions(root)
    registered = registered_markers(root)
    tests = root / "tests"
    if not tests.is_dir():
        return []

    # Keyed by distribution, holding a SET of files. A file that uses the marker
    # eight times is one file; appending per occurrence made the first run of
    # this module report "26 test file(s)" over a set of eight, which is the
    # uncounted magnitude AGENT-OPERATING-MEMORY forbids writing down.
    users: dict[str, set[Path]] = {}
    for path in sorted(tests.rglob("test_*.py")):
        for name in markers_used(_read(path)):
            if name in registered:
                continue
            distribution = MARKER_DISTRIBUTIONS.get(name)
            if distribution is None:
                continue
            if distribution.lower() in declared:
                continue
            users.setdefault(distribution, set()).add(path)

    candidates: list[Candidate] = []
    for distribution, paths in sorted(users.items()):
        relative = sorted(str(path.relative_to(root)) for path in paths)
        lanes = [lane_for_path(item) for item in relative]
        placed = [lane for lane in lanes if lane is not None]
        # The lane of the *most important* affected file. A gap spanning four
        # lanes is worked at the rank of the highest one, because that is the
        # capability that is unverified for longest if it waits.
        lane = min(placed, key=lambda item: item.rank) if placed else None
        evidence = tuple(
            Evidence(
                kind="marker-without-distribution",
                where=item,
                detail=f"uses a pytest marker supplied by {distribution!r}, which no requirements file declares",
            )
            for item in relative
        )
        unbound = [item for item, found in zip(relative, lanes) if found is None]
        candidates.append(
            Candidate(
                source="dependency-gap",
                title=(
                    f"Declare {distribution} so {len(relative)} test file(s) execute "
                    "instead of reporting unrun"
                ),
                summary=(
                    f"{len(relative)} test file(s) use a pytest marker that {distribution} "
                    "supplies, and no requirements file in this repository declares it. "
                    "Without the distribution pytest never runs those test bodies; it "
                    "reports them as failures whose assertions never executed, so every "
                    "capability they certify is currently unverified rather than failing."
                    + (
                        f" {len(unbound)} of the affected file(s) match no product lane "
                        "and are listed as evidence without being assigned one."
                        if unbound
                        else ""
                    )
                ),
                lane=lane,
                evidence=evidence,
                semantic_key=f"dependency-gap:{distribution}:" + ",".join(sorted(relative)),
                proposed_remedy=(
                    f"Add a pinned {distribution} requirement to requirements-dev.txt and "
                    "install it wherever CI installs that file, then re-run the affected "
                    "files and record the restored result."
                ),
                remedy=declare_remedy("dependency-gap", distribution),
                capabilities=("test-execution",),
                validation_command=covering_validation_command(relative),
            )
        )
    return candidates


def discover_failing_tests(report_text: str, root: Path) -> list[Candidate]:
    """One candidate per test file a pytest run reported failing.

    Grouped by file rather than by node id on purpose: a lane executes one
    bounded task, and six node ids in one module are one defect far more often
    than six. A run that produced no pytest summary line is refused outright —
    an empty failure set from a run that never collected anything is
    indistinguishable from a green run, and reading it as green is how a
    comparison over two empty sets once reported "zero new failures".
    """
    if report_text and not PYTEST_SUMMARY.search(report_text):
        raise ValueError(
            "pytest report carries no summary line; refusing to read it as a result"
        )

    by_file: dict[str, list[tuple[str, str]]] = {}
    for match in PYTEST_OUTCOME.finditer(report_text or ""):
        nodeid = match.group("nodeid")
        path = nodeid.split("::", 1)[0]
        if not path.endswith(".py"):
            continue
        by_file.setdefault(path, []).append((match.group("outcome"), nodeid))

    candidates: list[Candidate] = []
    for path, rows in sorted(by_file.items()):
        lane = lane_for_path(path)
        outcomes = sorted({outcome for outcome, _ in rows})
        node_ids = sorted(nodeid for _, nodeid in rows)
        evidence = tuple(
            Evidence(kind="pytest-outcome", where=nodeid, detail=outcome)
            for outcome, nodeid in sorted(rows, key=lambda row: row[1])
        )
        candidates.append(
            Candidate(
                source="failing-test",
                title=f"Repair {len(node_ids)} {'/'.join(outcomes).lower()} test(s) in {Path(path).name}",
                summary=(
                    f"A pytest run reported {len(node_ids)} {'/'.join(outcomes).lower()} "
                    f"result(s) in {path}. The node ids are listed as evidence; each is a "
                    "statement the repository makes about itself and currently does not keep."
                ),
                lane=lane,
                evidence=evidence,
                # Keyed on the node ids, so fixing four of six changes the
                # condition and produces a new, smaller candidate rather than
                # silently matching the old one.
                semantic_key="failing-test:" + ",".join(node_ids),
                capabilities=("test-execution",),
                validation_command=covering_validation_command([path]),
            )
        )
    return candidates


#: Trees whose imports are production dependencies. Tests are excluded: a test
#: may legitimately import a dev-only distribution.
RUNTIME_IMPORT_ROOTS = ("app", "runtime")

#: The registered command that proves an undeclared-import remedy: the base
#: application imports under the installed distributions. Bound only when
#: every affected file is inside the production trees that command exercises;
#: a finding elsewhere names no command and stays filed-but-unexecutable.
PRODUCTION_IMPORTS_COMMAND = "production-runtime-imports"


def import_validation_command(paths: list[str]) -> str:
    """The command that settles an undeclared-import candidate, or "".

    A literally covering command still wins when one exists. Otherwise the
    production import check applies to files under ``app/`` or ``runtime/``
    only -- the trees ``import app.main`` can reach -- and to nothing else.
    """
    covering = covering_validation_command(paths)
    if covering:
        return covering
    if not paths or PRODUCTION_IMPORTS_COMMAND not in VALIDATION_COMMANDS:
        return ""
    roots = tuple(f"{root}/" for root in RUNTIME_IMPORT_ROOTS)
    if all(path.startswith(roots) for path in paths):
        return PRODUCTION_IMPORTS_COMMAND
    return ""


def _imported_modules(source: str) -> set[str]:
    """Top-level module names a file imports, parsed rather than matched."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".", 1)[0])
    return {name for name in names if name and not name.startswith("_")}


def discover_undeclared_imports(root: Path, *, provided_by: dict[str, list[str]] | None = None) -> list[Candidate]:
    """Production code importing a distribution no requirements file declares.

    The repository runs on whatever `requirements*.txt` installs. A module that
    arrives only as somebody else's transitive dependency works until that
    somebody changes their pin, and then it does not -- in a deployment, not in
    a test.

    Which distribution provides a module is **asked, not guessed**:
    ``importlib.metadata.packages_distributions()`` reports what is actually
    installed. A first draft mapped module names to distributions by hand and
    got two of three findings wrong -- ``googleapiclient`` read as undeclared
    although ``google-api-python-client`` declares it, and a sibling script
    imported by path read as a missing package. Both disappear here, because a
    module no installed distribution provides is not reported at all, and
    neither is one whose provider is ambiguous.

    That makes this source fail closed on an incomplete environment: a
    distribution that is not installed yields no finding. Silence is the safe
    direction, and it is stated here so nobody reads silence as coverage.
    """
    provides = packages_distributions() if provided_by is None else provided_by
    declared = declared_distributions(root)
    standard = set(sys.stdlib_module_names)

    users: dict[str, set[str]] = {}
    for tree_root in RUNTIME_IMPORT_ROOTS:
        base = root / tree_root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            for module in _imported_modules(_read(path)):
                if module in standard:
                    continue
                distributions = {name.lower().replace("_", "-") for name in provides.get(module, [])}
                if len(distributions) != 1:
                    # Unprovided (local, or not installed) or ambiguous. Both
                    # are answers this module declines to turn into work.
                    continue
                distribution = distributions.pop()
                if distribution in declared:
                    continue
                users.setdefault(distribution, set()).add(str(path.relative_to(root)))

    candidates: list[Candidate] = []
    for distribution, paths in sorted(users.items()):
        relative = sorted(paths)
        lanes = [lane_for_path(item) for item in relative]
        placed = [lane for lane in lanes if lane is not None]
        lane = min(placed, key=lambda item: item.rank) if placed else None
        candidates.append(
            Candidate(
                source="undeclared-import",
                title=f"Declare {distribution}, which {len(relative)} production file(s) import directly",
                summary=(
                    f"{len(relative)} file(s) under {'/'.join(RUNTIME_IMPORT_ROOTS)} import a module "
                    f"that the installed {distribution} distribution provides, and no requirements "
                    "file declares it. It is reaching the deployment only as another dependency's "
                    "transitive install, which holds until that dependency changes its pin."
                ),
                lane=lane,
                evidence=tuple(
                    Evidence(
                        kind="undeclared-direct-import",
                        where=item,
                        detail=f"imports a module provided by {distribution!r}, which no requirements file declares",
                    )
                    for item in relative
                ),
                semantic_key=f"undeclared-import:{distribution}:" + ",".join(relative),
                proposed_remedy=(
                    f"Add {distribution} to requirements.txt with a pin consistent with the "
                    "dependency that currently supplies it, so the deployment declares what it imports."
                ),
                remedy=declare_remedy("undeclared-import", distribution),
                capabilities=("schema-validation",),
                validation_command=import_validation_command(relative),
            )
        )
    return candidates


#: The Brain's own gap record, produced by BUILD-016 knowledge-gap discovery.
BRAIN_GAP_STORE = "runtime/knowledge_gaps/latest.json"

#: How old the Brain's statement may be before this module stops presenting it
#: as current. It is not a deadline for the Brain; it is a label on the reading.
BRAIN_STALE_AFTER_DAYS = 30


def brain_observations(root: Path, *, now: datetime | None = None) -> dict[str, Any]:
    """What the Brain currently says is missing, and how old that statement is.

    The Brain is part of prioritisation here, and deliberately not part of
    materialisation. Its gaps are keyword-coverage statements over a runtime
    snapshot -- the evidence on each one reads ``Matched runtime items: 0`` --
    and its proposed actions are template sentences of the form "Add or connect
    <domain> data sources, validators, and review-ready outputs". Filing those
    as engineering tasks would be the invention this module exists to refuse:
    the record says Taxonomy has zero matched items while ``app/`` plainly has
    taxonomy modules, because the scan read discovery memory rather than the
    tree.

    So the Brain's reading is surfaced, with its age stated, and nothing is
    filed from it. A stale reading presented as current is the same defect as
    an unrun test presented as a failure.
    """
    path = root / BRAIN_GAP_STORE
    try:
        record = json.loads(_read(path))
    except (ValueError, TypeError):
        record = None
    if not isinstance(record, dict):
        return {
            "available": False,
            "source": BRAIN_GAP_STORE,
            "reason": "no readable Brain knowledge-gap record",
        }

    generated_at = str(record.get("generated_at") or "")
    age_days: int | None = None
    try:
        produced = datetime.fromisoformat(generated_at)
        if produced.tzinfo is None:
            produced = produced.replace(tzinfo=timezone.utc)
        age_days = max(0, ((now or datetime.now(timezone.utc)) - produced).days)
    except ValueError:
        age_days = None

    gaps = [gap for gap in (record.get("gaps") or []) if isinstance(gap, dict)]
    return {
        "available": True,
        "source": BRAIN_GAP_STORE,
        "build": record.get("build"),
        "generated_at": generated_at or None,
        "age_days": age_days,
        # Unknown age is reported stale. "We could not tell how old this is" is
        # not a reason to present it as current.
        "stale": age_days is None or age_days > BRAIN_STALE_AFTER_DAYS,
        "gap_count": len(gaps),
        "domains": sorted(
            {str(gap.get("domain")) for gap in gaps if gap.get("domain")}
        ),
        "critical_domains": sorted(
            {
                str(gap.get("domain"))
                for gap in gaps
                if gap.get("domain") and str(gap.get("priority", "")).upper() == "CRITICAL"
            }
        ),
        "materialised": False,
        "why_not_materialised": (
            "each gap's evidence is a keyword-coverage count over a runtime snapshot "
            "and its proposed action is a template sentence, neither of which names a "
            "checkable engineering condition; filing them would be inventing work"
        ),
    }


def evidence_path(where: str) -> str:
    """The repository path an evidence locator names.

    A pytest node id carries its file before the first ``::``; a path is
    already a path. Nothing else is inferred from the locator.
    """
    return str(where or "").split("::", 1)[0]


def binding_questions(candidates: list[Candidate]) -> list[Candidate]:
    """Turn every unplaced candidate into one bounded analysis task.

    Not one per unplaced candidate: the question is always the same shape — the
    lane table does not cover these paths — and asking it once per finding
    floods the queue with the discoverer's own uncertainty.
    """
    unplaced = [item for item in candidates if item.lane is None and not item.analysis_only]
    if not unplaced:
        return []
    # Evidence ``where`` is a repository path OR a pytest node id
    # (``tests/test_x.py::test_a``). The lane table binds paths, so the
    # question is asked about the file, once, however many of its tests
    # failed. Asking it per node id counted thirteen "paths" for one file and
    # gave the question a new identity every time a different test in that
    # file went red -- an uncounted magnitude and a churning fingerprint.
    paths = sorted({evidence_path(item.where) for candidate in unplaced for item in candidate.evidence})
    return [
        Candidate(
            source="binding-gap",
            title=f"Bind {len(paths)} discovered path(s) to an Orchid Continuum lane",
            summary=(
                "Work discovery found real evidence at these paths and the lane table in "
                "scripts/oc_product_lanes.py does not cover them, so no capability was "
                "assigned. Resolve it from repository evidence — the module each path "
                "belongs to, the routes it serves, the graph node that names it — and "
                "extend the table. Assigning the closest-looking lane is the failure this "
                "task exists to prevent; if the evidence genuinely does not decide it, "
                "that is an owner product decision and should be escalated as one."
            ),
            lane=None,
            evidence=tuple(
                Evidence(kind="unbound-path", where=path, detail="matches no product lane prefix")
                for path in paths
            ),
            semantic_key="binding-gap:" + ",".join(paths),
            analysis_only=True,
            capabilities=("reconcile",),
        )
    ]


def discover(root: Path, *, pytest_report: str = "") -> dict[str, Any]:
    """Run every source and return a ranked, deduplicated report."""
    candidates = discover_dependency_gaps(root)
    candidates.extend(discover_undeclared_imports(root))
    candidates.extend(discover_failing_tests(pytest_report, root))

    # A dependency gap explains the tests it stops from running, so a failing
    # test in a file the gap already names is not separate work. Emitting both
    # would put two lanes on one defect and have the second report a phantom
    # failure once the first lands.
    explained = {
        item.where
        for candidate in candidates
        if candidate.source == "dependency-gap"
        for item in candidate.evidence
    }
    deduplicated = [
        candidate
        for candidate in candidates
        if candidate.source != "failing-test"
        or not any(item.where.split("::", 1)[0] in explained for item in candidate.evidence)
    ]
    suppressed = [
        candidate.semantic_key for candidate in candidates if candidate not in deduplicated
    ]

    deduplicated.extend(binding_questions(deduplicated))
    deduplicated.sort(key=lambda item: (rank_of(item.lane), item.source, item.title))

    return {
        "schema": REPORT_SCHEMA,
        "brain": brain_observations(root),
        # Which sources this pass actually evaluated. The materializer treats a
        # condition's absence as evidence only when its source ran: without a
        # pytest report the failing-test source saw nothing, which is not the
        # same as seeing no failures.
        "sources_evaluated": sorted(
            {"dependency-gap", "undeclared-import", "binding-gap"}
            | ({"failing-test"} if pytest_report.strip() else set())
        ),
        "candidate_count": len(deduplicated),
        "candidates": [candidate.to_record() for candidate in deduplicated],
        "suppressed_by_dependency_gap": sorted(suppressed),
        "safety": {
            "provider_calls": False,
            "github_mutation": False,
            "repository_writes": False,
            "invented_work": False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="repository root to read")
    parser.add_argument(
        "--pytest-report",
        default="",
        help="path to captured pytest output; omitted means dependency gaps only",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    report_text = ""
    if args.pytest_report:
        report_text = _read(Path(args.pytest_report))
    json.dump(discover(root, pytest_report=report_text), sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
