"""Decision Fabric v1.

Models interpret meaning. This module owns deterministic validation, threshold
routing, source-field contracts, and durable result shape. Provider adapters are
pluggable; Jev is optional and no provider is imported here.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping, Protocol, Sequence


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

    def with_thresholds(self, *, accept: float | None = None, escalate: float | None = None) -> "DecisionSpec":
        return replace(
            self,
            accept_confidence=self.accept_confidence if accept is None else accept,
            escalate_confidence=self.escalate_confidence if escalate is None else escalate,
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
    def classify(self, spec: DecisionSpec, state: Mapping[str, Any]) -> DecisionResult: ...


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
            raise DecisionContractError("thresholds must satisfy 0 <= escalate <= accept <= 1")
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
                raise DecisionContractError(f"{q.id} must permit an explicit uncertainty escape")
            if q.type == "choice" and not q.options:
                raise DecisionContractError(f"{q.id} choice has no options")

    @classmethod
    def validate_result(cls, spec: DecisionSpec, result: DecisionResult, state: Mapping[str, Any]) -> None:
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
                raise DecisionContractError(f"answer for undeclared question {a.question_id}")
            if not 0 <= a.confidence <= 1:
                raise DecisionContractError(f"{a.question_id} confidence outside [0,1]")
            for field in a.source_fields_used:
                if field not in q.allowed_source_fields:
                    raise DecisionContractError(f"{a.question_id} used forbidden source field {field}")
                if field not in state:
                    raise DecisionContractError(f"{a.question_id} claims missing source field {field}")
            if q.type == "choice":
                allowed = set(q.options) | cls.ESCAPES
                if a.answer not in allowed:
                    raise DecisionContractError(f"{a.question_id} returned undeclared choice {a.answer!r}")
            if q.type == "boolean" and not (isinstance(a.answer, bool) or a.answer in cls.ESCAPES):
                raise DecisionContractError(f"{a.question_id} must be boolean or uncertainty escape")
            if a.probabilities:
                total = sum(float(v) for v in a.probabilities.values())
                if any(float(v) < 0 or float(v) > 1 for v in a.probabilities.values()):
                    raise DecisionContractError(f"{a.question_id} has probability outside [0,1]")
                if total > 1.000001:
                    raise DecisionContractError(f"{a.question_id} probabilities sum above 1")
        missing = set(by_id) - seen
        if missing:
            raise DecisionContractError(f"missing answers: {sorted(missing)}")

    @classmethod
    def route(cls, spec: DecisionSpec, result: DecisionResult) -> RouteOutcome:
        cls.validate_spec(spec)
        min_conf = min(a.confidence for a in result.answers)
        if min_conf >= spec.accept_confidence:
            return RouteOutcome("accepted", ("all answers meet accept threshold",), min_conf)
        if min_conf >= spec.escalate_confidence and len(spec.provider_policy) > 1:
            return RouteOutcome("escalate", ("one or more answers below accept threshold",), min_conf)
        return RouteOutcome("review", ("confidence below autonomous routing floor",), min_conf)

    def run(self, spec: DecisionSpec, state: Mapping[str, Any], adapter: DecisionAdapter) -> tuple[DecisionResult, RouteOutcome]:
        result = adapter.classify(spec, state)
        self.validate_result(spec, result, state)
        return result, self.route(spec, result)


def literature_triage_spec() -> DecisionSpec:
    return DecisionSpec(
        id="oc.literature-triage",
        version="1.0.0",
        questions=(
            DecisionQuestion("orchid_relevance","choice","Does the title/abstract materially concern Orchidaceae?",("title","abstract","keywords"),options=("direct","indirect","none","unknown")),
            DecisionQuestion("primary_data","choice","Does the text explicitly report primary observations, experiments or measurements?",("title","abstract"),options=("yes","no","unclear")),
            DecisionQuestion("topic","choice","Classify the primary OC scientific destination.",("title","abstract","keywords"),options=("taxonomy","pollination","mycorrhiza","conservation","ecology","genetics","morphology","horticulture","methods","other","unknown")),
            DecisionQuestion("full_text_warranted","boolean","Would full text likely add evidence needed by OC?",("title","abstract","keywords")),
        ),
        accept_confidence=0.80,
        escalate_confidence=0.55,
        provider_policy=("deterministic-cache","fast-classifier","strong-reasoner","human-review"),
    )


def autonomy_gate_spec() -> DecisionSpec:
    return DecisionSpec(
        id="oc.autonomy-gate",
        version="1.0.0",
        questions=(
            DecisionQuestion("blocker_type","choice","Classify the blocker from machine state.",("ci_status","mergeability","changed_files","task_metadata","lease_state"),options=("none","test_failure","contract_failure","dependency","authorization","spend","deployment","unknown")),
            DecisionQuestion("safe_to_merge","boolean","Is the change inside the configured safe autonomous merge boundary?",("ci_status","mergeability","changed_files","task_metadata")),
            DecisionQuestion("acceptance_met","boolean","Do evidence receipts satisfy declared acceptance?",("ci_status","acceptance_receipts","task_metadata")),
        ),
        accept_confidence=0.90,
        escalate_confidence=0.70,
        provider_policy=("deterministic-checks","reasoning-provider","human-gate"),
    )
