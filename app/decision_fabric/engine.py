"""Decision Fabric v1.

Models interpret meaning. This module owns deterministic validation, threshold
routing, source-field contracts, and durable result shape. Provider adapters are
pluggable; Jev is optional and no provider is imported here.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol

#: The Brain's contract, vendored verbatim from Orchid-Continuum-Brain
#: contracts/decision_fabric_v1.json (PR #159). The reference specs below are
#: built from it rather than restated by hand, so the two cannot drift.
CONTRACT_PATH = (
    Path(__file__).resolve().parents[2] / "contracts" / "decision_fabric_v1.json"
)
CONTRACT_SCHEMA = "oc.decision-fabric.v1"
#: sha256 of the vendored file as pinned. A vendored copy that does not match is
#: refused: a changed contract must be re-vendored and re-pinned deliberately.
BRAIN_CONTRACT_SHA256 = (
    "ab05b53839bfac45727410ae6334c8c405ad21235e8c97081cd9b11eea6198ba"
)
#: Policy entries that hand the decision to a person are not "a stronger
#: configured provider": reaching one is the review state, not an escalation.
HUMAN_PROVIDER_PREFIX = "human"


@dataclass(frozen=True)
class DecisionQuestion:
    id: str
    type: str
    instructions: str
    allowed_source_fields: tuple[str, ...]
    unknown_allowed: bool = True
    options: tuple[str, ...] = ()


@dataclass(frozen=True)
class DecisionSpec:
    id: str
    version: str
    questions: tuple[DecisionQuestion, ...]
    accept_confidence: float
    escalate_confidence: float
    provider_policy: tuple[str, ...]

    def with_thresholds(
        self, *, accept: float | None = None, escalate: float | None = None
    ) -> DecisionSpec:
        return replace(
            self,
            accept_confidence=self.accept_confidence if accept is None else accept,
            escalate_confidence=self.escalate_confidence
            if escalate is None
            else escalate,
        )


@dataclass(frozen=True)
class DecisionAnswer:
    question_id: str
    answer: Any
    confidence: float
    probabilities: Mapping[str, float]
    source_fields_used: tuple[str, ...]


@dataclass(frozen=True)
class DecisionResult:
    spec_id: str
    spec_version: str
    provider: str
    provider_model: str
    answers: tuple[DecisionAnswer, ...]
    latency_ms: float
    input_tokens: int
    cost_usd: float


@dataclass(frozen=True)
class RouteOutcome:
    state: str
    reasons: tuple[str, ...]
    min_confidence: float


class DecisionAdapter(Protocol):
    name: str
    model: str

    def classify(
        self, spec: DecisionSpec, state: Mapping[str, Any]
    ) -> DecisionResult: ...


class DecisionContractError(ValueError):
    pass


class StaticDecisionAdapter:
    """Test/offline adapter. It returns a precomputed result and never calls a provider."""

    def __init__(self, result: DecisionResult):
        self._result = result
        self.name = result.provider
        self.model = result.provider_model
        self.calls = 0

    def classify(self, spec: DecisionSpec, state: Mapping[str, Any]) -> DecisionResult:
        self.calls += 1
        return self._result


class DecisionEngine:
    """Validate provider output, then make routing decisions in code."""

    ESCAPES = frozenset({"unknown", "unclear", "not_stated", "other"})

    @staticmethod
    def validate_spec(spec: DecisionSpec) -> None:
        if not (0 <= spec.escalate_confidence <= spec.accept_confidence <= 1):
            raise DecisionContractError(
                "thresholds must satisfy 0 <= escalate <= accept <= 1"
            )
        if not spec.questions:
            raise DecisionContractError("spec must contain questions")
        ids = [q.id for q in spec.questions]
        if len(ids) != len(set(ids)):
            raise DecisionContractError("question ids must be unique")
        for q in spec.questions:
            if q.type not in {"choice", "score", "boolean", "extraction"}:
                raise DecisionContractError(f"unsupported question type {q.type!r}")
            if not q.allowed_source_fields:
                raise DecisionContractError(f"{q.id} declares no allowed source fields")
            if not q.unknown_allowed:
                raise DecisionContractError(
                    f"{q.id} must permit an explicit uncertainty escape"
                )
            if q.type == "choice" and not q.options:
                raise DecisionContractError(f"{q.id} choice has no options")

    @classmethod
    def validate_result(
        cls, spec: DecisionSpec, result: DecisionResult, state: Mapping[str, Any]
    ) -> None:
        cls.validate_spec(spec)
        if result.spec_id != spec.id or result.spec_version != spec.version:
            raise DecisionContractError("result does not match spec identity/version")
        by_id = {q.id: q for q in spec.questions}
        seen: set[str] = set()
        for a in result.answers:
            if a.question_id in seen:
                raise DecisionContractError(f"duplicate answer for {a.question_id}")
            seen.add(a.question_id)
            q = by_id.get(a.question_id)
            if q is None:
                raise DecisionContractError(
                    f"answer for undeclared question {a.question_id}"
                )
            if not 0 <= a.confidence <= 1:
                raise DecisionContractError(f"{a.question_id} confidence outside [0,1]")
            for field in a.source_fields_used:
                if field not in q.allowed_source_fields:
                    raise DecisionContractError(
                        f"{a.question_id} used forbidden source field {field}"
                    )
                if field not in state:
                    raise DecisionContractError(
                        f"{a.question_id} claims missing source field {field}"
                    )
            if q.type == "choice":
                allowed = set(q.options) | cls.ESCAPES
                if a.answer not in allowed:
                    raise DecisionContractError(
                        f"{a.question_id} returned undeclared choice {a.answer!r}"
                    )
            if q.type == "boolean" and not (
                isinstance(a.answer, bool) or a.answer in cls.ESCAPES
            ):
                raise DecisionContractError(
                    f"{a.question_id} must be boolean or uncertainty escape"
                )
            if a.probabilities:
                total = sum(float(v) for v in a.probabilities.values())
                if any(float(v) < 0 or float(v) > 1 for v in a.probabilities.values()):
                    raise DecisionContractError(
                        f"{a.question_id} has probability outside [0,1]"
                    )
                if total > 1.000001:
                    raise DecisionContractError(
                        f"{a.question_id} probabilities sum above 1"
                    )
        missing = set(by_id) - seen
        if missing:
            raise DecisionContractError(f"missing answers: {sorted(missing)}")

    @staticmethod
    def stronger_providers(spec: DecisionSpec, provider: str) -> tuple[str, ...]:
        """Providers configured after ``provider`` in the policy, humans excluded.

        The Brain contract escalates only when "a stronger configured provider is
        available". That is a property of where the result's provider sits in
        the policy, not of the policy's length: a result from the strongest
        non-human provider has nowhere to go but review, and a provider the
        policy does not name cannot be said to have anything stronger after it.
        """
        policy = tuple(spec.provider_policy)
        if provider not in policy:
            return ()
        remaining = policy[policy.index(provider) + 1 :]
        return tuple(p for p in remaining if not p.startswith(HUMAN_PROVIDER_PREFIX))

    @classmethod
    def route(cls, spec: DecisionSpec, result: DecisionResult) -> RouteOutcome:
        cls.validate_spec(spec)
        min_conf = min(a.confidence for a in result.answers)
        if min_conf >= spec.accept_confidence:
            return RouteOutcome(
                "accepted", ("all answers meet accept threshold",), min_conf
            )
        if min_conf < spec.escalate_confidence:
            return RouteOutcome(
                "review", ("confidence below autonomous routing floor",), min_conf
            )
        stronger = cls.stronger_providers(spec, result.provider)
        if stronger:
            return RouteOutcome(
                "escalate",
                (
                    "one or more answers below accept threshold",
                    f"stronger configured provider available: {stronger[0]}",
                ),
                min_conf,
            )
        return RouteOutcome(
            "review",
            (
                "one or more answers below accept threshold",
                f"no stronger configured provider after {result.provider!r}",
            ),
            min_conf,
        )

    def run(
        self, spec: DecisionSpec, state: Mapping[str, Any], adapter: DecisionAdapter
    ) -> tuple[DecisionResult, RouteOutcome]:
        result = adapter.classify(spec, state)
        self.validate_result(spec, result, state)
        return result, self.route(spec, result)


def load_contract(
    path: Path | str = CONTRACT_PATH, *, verify: bool = True
) -> dict[str, Any]:
    """Read the vendored Brain contract, refusing a copy that is not the pinned one."""
    raw = Path(path).read_bytes()
    if verify:
        actual = hashlib.sha256(raw).hexdigest()
        if actual != BRAIN_CONTRACT_SHA256:
            raise DecisionContractError(
                f"vendored decision fabric contract drifted from its pin: "
                f"sha256 {actual[:12]}… != pinned {BRAIN_CONTRACT_SHA256[:12]}…; "
                "re-vendor from the Brain and update BRAIN_CONTRACT_SHA256 deliberately"
            )
    contract = json.loads(raw.decode("utf-8"))
    if not isinstance(contract, dict) or contract.get("schema") != CONTRACT_SCHEMA:
        raise DecisionContractError(
            f"decision fabric contract schema must be {CONTRACT_SCHEMA}"
        )
    return contract


def spec_from_contract(spec: Mapping[str, Any]) -> DecisionSpec:
    """Build a validated DecisionSpec from one ``reference_specs`` entry."""
    questions = tuple(
        DecisionQuestion(
            id=str(q["id"]),
            type=str(q["type"]),
            instructions=str(q["instructions"]),
            allowed_source_fields=tuple(q["allowed_source_fields"]),
            unknown_allowed=bool(q.get("unknown_allowed", True)),
            options=tuple(q.get("options", ())),
        )
        for q in spec["questions"]
    )
    built = DecisionSpec(
        id=str(spec["id"]),
        version=str(spec["version"]),
        questions=questions,
        accept_confidence=float(spec["accept_confidence"]),
        escalate_confidence=float(spec["escalate_confidence"]),
        provider_policy=tuple(spec["provider_policy"]),
    )
    DecisionEngine.validate_spec(built)
    return built


def load_reference_specs(
    path: Path | str = CONTRACT_PATH, *, verify: bool = True
) -> dict[str, DecisionSpec]:
    """Every reference spec the Brain contract declares, keyed by its name."""
    contract = load_contract(path, verify=verify)
    return {
        name: spec_from_contract(spec)
        for name, spec in contract["reference_specs"].items()
    }


def literature_triage_spec() -> DecisionSpec:
    return load_reference_specs()["literature_triage"]


def autonomy_gate_spec() -> DecisionSpec:
    return load_reference_specs()["autonomy_gate"]
