"""Which Orchid Continuum capability a repository path belongs to, and what it outranks.

Work discovery has to answer two questions about every piece of evidence it
finds: *what product capability does this concern*, and *should it be worked
before the other thing I found*. Both answers have to come from something
checkable, because the alternative is a discoverer that reads a file name and
tells a story about it — and a queue full of invented work costs more than an
empty one.

So the binding is a path prefix, matched against the repository tree, and the
priority is the owner's stated lane order. A path that matches no lane produces
no lane. It is reported as unbound and, where a task is warranted at all, it
becomes a bounded analysis task rather than a guess — the same rule the graph
binding already follows on the frontend, for the same reason.

The lane order is the owner's, recorded here so it survives a session:

    Calyx → Illustrated Glossary / Lexicon → Literature and Journal Club
    → Research Station → Matrix ID → Atlas → Interaction Graph → Vision Lab
    → Improvement Discovery Loop

"unless repository dependencies require another sequence" is not encoded here
and must not be: a dependency edge is a fact about two specific tasks, and the
dependency graph the controller already runs is where that belongs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: ``oc-p0`` is reserved for control-plane emergencies the portfolio scheduler
#: already understands. Discovered product work starts below it so it can never
#: outrank an incident.
FIRST_PRODUCT_PRIORITY = 1
LOWEST_PRIORITY = 5


@dataclass(frozen=True)
class ProductLane:
    """One Orchid Continuum capability, and the paths that are part of it."""

    key: str
    name: str
    #: Rank in the owner's stated order; 1 is worked first.
    rank: int
    #: Repository path prefixes. Matched literally against a POSIX path, so a
    #: prefix is a statement about the tree rather than about a word.
    path_prefixes: tuple[str, ...]
    #: Substrings of a *test file's own name*. Tests live in one flat directory
    #: here, so a test's subject cannot be read from its parent directory the
    #: way a module's can.
    test_name_markers: tuple[str, ...] = ()

    @property
    def priority_label(self) -> str:
        return f"oc-p{min(LOWEST_PRIORITY, max(0, self.rank))}"

    @property
    def lane_label(self) -> str:
        return f"oc-lane:{self.key}"


#: Ordered by the owner's priority. The first lane whose evidence matches wins,
#: so a path that could belong to two lanes is worked under the higher one.
PRODUCT_LANES: tuple[ProductLane, ...] = (
    ProductLane(
        key="calyx",
        name="Calyx",
        rank=1,
        path_prefixes=(
            "app/calyx_agent/",
            "app/calyx_conversation/",
            "app/calyx_engineering/",
            "app/calyx_flywheel/",
            "app/calyx_journalism/",
            "app/canonical_brain/",
            "app/brain/",
            "app/brain_mission/",
            "app/reasoning_ledger/",
            "app/reasoning_publication/",
            "app/scientific_memory/",
            "runtime/brain_integration.py",
            "runtime/brain_router.py",
            "runtime/continuum_conversation.py",
        ),
        test_name_markers=("calyx_brain", "calyx_conversation", "reasoning_ledger", "brain_"),
    ),
    ProductLane(
        key="lexicon",
        name="Illustrated Glossary / Lexicon",
        rank=2,
        path_prefixes=("app/lexicon/", "app/vision_lexicon/", "app/ontology/", "app/concepts/"),
        test_name_markers=("glossary", "lexicon"),
    ),
    ProductLane(
        key="literature",
        name="Literature and Journal Club",
        rank=3,
        path_prefixes=(
            "app/literature_extraction/",
            "app/document_import/",
            "app/document_intelligence/",
            "app/publication/",
            "app/source_federation/",
            "app/source_registry/",
            "runtime/literature_harvester.py",
            "runtime/literature_staging.py",
        ),
        test_name_markers=("literature", "journal_club", "source_binding", "bibliograph"),
    ),
    ProductLane(
        key="research-station",
        name="Research Station",
        rank=3,
        path_prefixes=(
            "app/research_traits/",
            "app/research_workspace/",
            "app/scientific_synthesis/",
            "app/scientific_inference/",
            "app/scientific_interpretation/",
            "runtime/research_station.py",
            "runtime/research_analysis_workflow.py",
        ),
        test_name_markers=("research_station", "research_traits", "evidence_matrix", "syn_"),
    ),
    ProductLane(
        key="matrix-id",
        name="Matrix ID",
        rank=4,
        path_prefixes=("runtime/matrix_identification.py", "runtime/matrix_relationship.py"),
        test_name_markers=("matrix_identification", "matrix_relationship"),
    ),
    ProductLane(
        key="atlas",
        name="Atlas",
        rank=4,
        path_prefixes=("app/atlas_intelligence/", "runtime/occurrence_persistence.py",
                       "runtime/occurrence_staging.py", "runtime/globi_canonical_harvester.py"),
        test_name_markers=("atlas", "occurrence"),
    ),
    ProductLane(
        key="interaction-graph",
        name="Interaction Graph",
        rank=4,
        path_prefixes=("app/interaction_discovery/", "runtime/knowledge_graph/",
                       "runtime/continuum_graph_tool.py", "runtime/interaction_harvester.py"),
        test_name_markers=("interaction", "knowledge_graph", "kg_"),
    ),
    ProductLane(
        key="vision-lab",
        name="Vision Lab",
        rank=4,
        path_prefixes=("app/multimodal_intelligence/", "runtime/matrix_identification_vision.py",
                       "runtime/taxonomy_image_population.py", "runtime/image_staging.py"),
        test_name_markers=("vision", "multimodal", "image"),
    ),
    ProductLane(
        key="improvement-discovery",
        name="Improvement Discovery Loop",
        rank=5,
        path_prefixes=(
            "app/calyx_orchestrator/",
            "app/autonomy/",
            "runtime/autonomous_discovery.py",
            "runtime/autonomous_orchestrator.py",
            "runtime/self_audit.py",
            "scripts/oc_work_discovery.py",
        ),
        test_name_markers=("improvement", "self_audit", "work_discovery"),
    ),
)

LANES_BY_KEY = {lane.key: lane for lane in PRODUCT_LANES}

_TEST_FILE = re.compile(r"(?:^|/)test_(?P<stem>[a-z0-9_]+)\.py$")


def lane_for_path(path: str) -> ProductLane | None:
    """Return the lane a repository path belongs to, or ``None``.

    ``None`` is a real answer and the caller must keep it as one. The whole
    point of a prefix table is that an unmatched path is *reported* rather than
    assigned to whichever lane looks closest.
    """
    normalized = str(path or "").replace("\\", "/").lstrip("./")
    if not normalized:
        return None
    for lane in PRODUCT_LANES:
        if any(normalized.startswith(prefix) for prefix in lane.path_prefixes):
            return lane
    match = _TEST_FILE.search(normalized)
    if match:
        stem = match.group("stem")
        for lane in PRODUCT_LANES:
            if any(marker in stem for marker in lane.test_name_markers):
                return lane
    return None


def rank_of(lane: ProductLane | None) -> int:
    """Sort key for a lane. An unbound candidate sorts last, never first."""
    return lane.rank if lane is not None else LOWEST_PRIORITY + 1
