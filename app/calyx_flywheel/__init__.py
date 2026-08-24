"""Governed Calyx improvement flywheel contracts and simulation library.

Packet 1 (#1138) established procedure/assertion governance. Packet 2 (#1139)
adds deterministic scientific simulations and regression evaluation. Nothing in
this package autonomously publishes scientific knowledge or writes the graph.
"""

from app.calyx_flywheel.locality import (
    SENSITIVE_LOCALITY_FIELDS,
    SensitiveLocalityError,
    assert_no_sensitive_locality,
)
from app.calyx_flywheel.models import (
    AssertionKind,
    AssertionOrigin,
    GovernanceState,
    KnowledgeSuggestion,
    ModelIdentity,
    Procedure,
    ProcedureStep,
    ProvenanceAnchor,
    ReviewDecision,
    ReviewOutcome,
    ScientificAssertion,
    SimulationCase,
    SimulationRun,
    StepControl,
    SupersessionRecord,
)
from app.calyx_flywheel.simulations import (
    ExecutionMode,
    ExpectedInvariant,
    FixtureSimulationRunner,
    GovernedToolFixture,
    InvariantClass,
    InvariantOperator,
    InvariantResult,
    LiveCanaryPolicy,
    RegressionCase,
    SimulationArchive,
    SimulationObservation,
    SimulationReport,
    SimulationSnapshot,
    SimulationTurn,
    seed_regression_cases,
)

__all__ = [
    "SENSITIVE_LOCALITY_FIELDS",
    "AssertionKind",
    "AssertionOrigin",
    "ExecutionMode",
    "ExpectedInvariant",
    "FixtureSimulationRunner",
    "GovernanceState",
    "GovernedToolFixture",
    "InvariantClass",
    "InvariantOperator",
    "InvariantResult",
    "KnowledgeSuggestion",
    "LiveCanaryPolicy",
    "ModelIdentity",
    "Procedure",
    "ProcedureStep",
    "ProvenanceAnchor",
    "RegressionCase",
    "ReviewDecision",
    "ReviewOutcome",
    "ScientificAssertion",
    "SensitiveLocalityError",
    "SimulationArchive",
    "SimulationCase",
    "SimulationObservation",
    "SimulationReport",
    "SimulationRun",
    "SimulationSnapshot",
    "SimulationTurn",
    "StepControl",
    "SupersessionRecord",
    "assert_no_sensitive_locality",
    "seed_regression_cases",
]
