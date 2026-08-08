from __future__ import annotations

import ast
import io
import math
import os
import statistics
from statistics import NormalDist
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from app.evidence_retrieval.engine import RetrievalEngine
from app.evidence_retrieval.models import RetrievalQuery
from app.evidence_retrieval.routes import REPO
from app.security import verify_owner_or_api_key
from app.semantic_index.provider import DeterministicLocalProvider
from runtime.knowledge_graph import PostgresGraphRepository, canonical_key, traverse

from .store import ConversationStore

router = APIRouter(
    prefix="/calyx",
    tags=["calyx-conversation"],
    dependencies=[Depends(verify_owner_or_api_key)],
)

ENGINE = RetrievalEngine(REPO, DeterministicLocalProvider())
STORE = ConversationStore()


class AnalysisRequest(BaseModel):
    operation: Literal[
        "expression",
        "summary",
        "correlation",
        "covariance",
        "linear_regression",
        "percent_change",
        "confidence_interval_mean",
        "moving_average",
    ]
    expression: str | None = None
    values: list[float] = Field(default_factory=list, max_length=100000)
    x: list[float] = Field(default_factory=list, max_length=100000)
    y: list[float] = Field(default_factory=list, max_length=100000)
    confidence: float = Field(0.95, gt=0.5, lt=1.0)
    window: int = Field(3, ge=2, le=10000)


class DatasetAnalysisRequest(BaseModel):
    operation: Literal["describe", "correlation_matrix"] = "describe"
    columns: dict[str, list[Any]] = Field(default_factory=dict)


class GraphContextRequest(BaseModel):
    node_id: int | None = Field(None, gt=0)
    taxon_id: str | None = Field(None, min_length=1, max_length=200)
    genus: str | None = Field(None, min_length=1, max_length=200)
    depth: int = Field(1, ge=1, le=3)
    limit: int = Field(50, ge=1, le=250)


class BrainQueryRequest(BaseModel):
    node_type: str | None = Field(None, min_length=1, max_length=100)
    canonical_key: str | None = Field(None, min_length=1, max_length=500)
    edge_type: str | None = Field(None, min_length=1, max_length=100)
    text: str | None = Field(None, min_length=1, max_length=500)
    limit: int = Field(50, ge=1, le=250)


class ConversationRequest(BaseModel):
    message: str = Field(min_length=1, max_length=5000)
    conversation_id: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    analysis: AnalysisRequest | None = None
    dataset_analysis: DatasetAnalysisRequest | None = None
    graph_context: GraphContextRequest | None = None
    brain_query: BrainQueryRequest | None = None
    retrieval_mode: Literal["LEXICAL", "SEMANTIC", "HYBRID"] = "HYBRID"
    limit: int = Field(8, ge=1, le=25)
    internal_access: bool = True
    include_history: bool = True


_ALLOWED_BINOPS = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.FloorDiv: lambda a, b: a // b,
    ast.Mod: lambda a, b: a % b,
    ast.Pow: lambda a, b: a**b,
}
_ALLOWED_UNARY = {ast.UAdd: lambda a: +a, ast.USub: lambda a: -a}
_ALLOWED_FUNCS = {
    "abs": abs,
    "round": round,
    "sqrt": math.sqrt,
    "log": math.log,
    "log10": math.log10,
    "exp": math.exp,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
}
_ALLOWED_CONSTS = {"pi": math.pi, "e": math.e}


def _eval_math(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval_math(node.body)
    if (
        isinstance(node, ast.Constant)
        and isinstance(node.value, (int, float))
        and not isinstance(node.value, bool)
    ):
        return float(node.value)
    if isinstance(node, ast.Name) and node.id in _ALLOWED_CONSTS:
        return float(_ALLOWED_CONSTS[node.id])
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
        return float(
            _ALLOWED_BINOPS[type(node.op)](
                _eval_math(node.left), _eval_math(node.right)
            )
        )
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARY:
        return float(_ALLOWED_UNARY[type(node.op)](_eval_math(node.operand)))
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in _ALLOWED_FUNCS
    ):
        if node.keywords:
            raise ValueError("keyword arguments are not supported")
        return float(
            _ALLOWED_FUNCS[node.func.id](*[_eval_math(arg) for arg in node.args])
        )
    raise TypeError("unsupported mathematical expression")


def safe_expression(expression: str) -> float:
    if len(expression) > 500:
        raise ValueError("expression too long")
    tree = ast.parse(expression, mode="eval")
    for node in ast.walk(tree):
        if isinstance(
            node,
            (
                ast.Attribute,
                ast.Subscript,
                ast.Lambda,
                ast.Dict,
                ast.ListComp,
                ast.GeneratorExp,
                ast.SetComp,
            ),
        ):
            raise TypeError("unsupported mathematical expression")
    result = _eval_math(tree)
    if not math.isfinite(result):
        raise ValueError("mathematical result is not finite")
    return result


def _paired_stats(
    x: list[float], y: list[float]
) -> tuple[float, float, float, float, float]:
    if len(x) != len(y) or len(x) < 2:
        raise ValueError(
            "x and y must have the same length and at least two observations"
        )
    mean_x = statistics.fmean(x)
    mean_y = statistics.fmean(y)
    sxx = sum((v - mean_x) ** 2 for v in x)
    syy = sum((v - mean_y) ** 2 for v in y)
    sxy = sum((a - mean_x) * (b - mean_y) for a, b in zip(x, y))
    return mean_x, mean_y, sxx, syy, sxy


def run_analysis(request: AnalysisRequest) -> dict[str, Any]:
    op = request.operation
    if op == "expression":
        if not request.expression:
            raise ValueError("expression is required")
        return {"operation": op, "result": safe_expression(request.expression)}

    if op == "summary":
        values = request.values
        if not values:
            raise ValueError("values are required")
        quartiles = (
            statistics.quantiles(values, n=4, method="inclusive")
            if len(values) > 1
            else [values[0]] * 3
        )
        result: dict[str, Any] = {
            "count": len(values),
            "sum": sum(values),
            "mean": statistics.fmean(values),
            "median": statistics.median(values),
            "min": min(values),
            "q1": quartiles[0],
            "q3": quartiles[2],
            "max": max(values),
        }
        if len(values) > 1:
            result["stdev_sample"] = statistics.stdev(values)
            result["variance_sample"] = statistics.variance(values)
            result["standard_error"] = statistics.stdev(values) / math.sqrt(len(values))
        return {"operation": op, "result": result}

    if op in {"correlation", "covariance", "linear_regression"}:
        mean_x, mean_y, sxx, syy, sxy = _paired_stats(request.x, request.y)
        if op == "covariance":
            return {
                "operation": op,
                "result": sxy / (len(request.x) - 1),
                "n": len(request.x),
            }
        if sxx == 0:
            raise ValueError("x has zero variance")
        if op == "correlation":
            if syy == 0:
                raise ValueError("y has zero variance")
            return {
                "operation": op,
                "result": sxy / math.sqrt(sxx * syy),
                "n": len(request.x),
            }
        slope = sxy / sxx
        intercept = mean_y - slope * mean_x
        r_squared = (sxy * sxy) / (sxx * syy) if syy else 1.0
        predictions = [intercept + slope * value for value in request.x]
        residual_sum_squares = sum(
            (observed - predicted) ** 2
            for observed, predicted in zip(request.y, predictions)
        )
        return {
            "operation": op,
            "result": {
                "slope": slope,
                "intercept": intercept,
                "r_squared": r_squared,
                "residual_sum_squares": residual_sum_squares,
                "n": len(request.x),
            },
        }

    if op == "percent_change":
        if len(request.values) != 2:
            raise ValueError("percent_change requires exactly two values: old, new")
        old, new = request.values
        if old == 0:
            raise ValueError("old value cannot be zero")
        return {
            "operation": op,
            "result": ((new - old) / old) * 100.0,
            "old": old,
            "new": new,
        }

    if op == "confidence_interval_mean":
        values = request.values
        if len(values) < 2:
            raise ValueError("confidence_interval_mean requires at least two values")
        mean = statistics.fmean(values)
        standard_error = statistics.stdev(values) / math.sqrt(len(values))
        z = NormalDist().inv_cdf(0.5 + request.confidence / 2.0)
        margin = z * standard_error
        return {
            "operation": op,
            "result": {
                "mean": mean,
                "lower": mean - margin,
                "upper": mean + margin,
                "confidence": request.confidence,
                "standard_error": standard_error,
                "method": "normal-approximation",
                "n": len(values),
                "approximation_only": True,
                "canonical_scientific_method": False,
                "research_grade": False,
                "p_value_generated": False,
                "scientific_interpretation_generated": False,
                "governed_research_method": "CALYX-617 Student-t mean confidence interval (not yet live)",
                "warning": (
                    "Approximation-only convenience interval. Do not treat this normal-approximation "
                    "result as the governed Research Station confidence interval; small-sample mean "
                    "inference requires the CALYX-617 Student-t method."
                ),
            },
        }

    if op == "moving_average":
        if len(request.values) < request.window:
            raise ValueError("moving_average window cannot exceed number of values")
        output = [
            statistics.fmean(request.values[i : i + request.window])
            for i in range(len(request.values) - request.window + 1)
        ]
        return {
            "operation": op,
            "result": output,
            "window": request.window,
            "n": len(request.values),
        }

    raise ValueError("unsupported analysis operation")


def _numeric(values: list[Any]) -> list[float]:
    result: list[float] = []
    for value in values:
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, (int, float)):
            number = float(value)
            if math.isfinite(number):
                result.append(number)
    return result


def run_dataset_analysis(request: DatasetAnalysisRequest) -> dict[str, Any]:
    if not request.columns:
        raise ValueError("dataset columns are required")
    lengths = {len(values) for values in request.columns.values()}
    if len(lengths) != 1:
        raise ValueError("all dataset columns must have the same row count")
    row_count = next(iter(lengths)) if lengths else 0
    if row_count > 100000:
        raise ValueError("dataset exceeds 100000 rows")

    if request.operation == "describe":
        columns: dict[str, Any] = {}
        for name, raw in request.columns.items():
            numeric = _numeric(raw)
            column: dict[str, Any] = {
                "rows": row_count,
                "missing_or_non_numeric": row_count - len(numeric),
                "numeric_count": len(numeric),
            }
            if numeric:
                summary = run_analysis(
                    AnalysisRequest(operation="summary", values=numeric)
                )["result"]
                column.update(summary)
            columns[name] = column
        return {
            "operation": request.operation,
            "row_count": row_count,
            "columns": columns,
        }

    numeric_columns = {
        name: _numeric(values) for name, values in request.columns.items()
    }
    matrix: dict[str, dict[str, float | None]] = {}
    for left, left_values in numeric_columns.items():
        matrix[left] = {}
        for right, right_values in numeric_columns.items():
            if (
                len(left_values) != row_count
                or len(right_values) != row_count
                or row_count < 2
            ):
                matrix[left][right] = None
                continue
            try:
                matrix[left][right] = run_analysis(
                    AnalysisRequest(
                        operation="correlation", x=left_values, y=right_values
                    )
                )["result"]
            except ValueError:
                matrix[left][right] = None
    return {"operation": request.operation, "row_count": row_count, "matrix": matrix}


def _graph_repository() -> PostgresGraphRepository:
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise ValueError("Knowledge Graph database is not configured")
    return PostgresGraphRepository(dsn)


def run_graph_context(request: GraphContextRequest) -> dict[str, Any]:
    repo = _graph_repository()
    focal = None
    requested = None
    if request.node_id is not None:
        requested = {"type": "node_id", "value": request.node_id}
        focal = repo.get_node(request.node_id)
    elif request.taxon_id:
        requested = {"type": "taxon_id", "value": request.taxon_id}
        key = (
            request.taxon_id
            if ":" in request.taxon_id
            else canonical_key("taxon", request.taxon_id)
        )
        focal = repo.get_node_by_key(key)
    elif request.genus:
        requested = {"type": "genus", "value": request.genus}
        focal = repo.find_genus_node(request.genus)
    else:
        raise ValueError("graph_context requires node_id, taxon_id, or genus")
    if focal is None:
        return {"requested": requested, "found": False, "nodes": [], "edges": []}
    result = traverse(repo, focal, depth=request.depth, limit=request.limit, offset=0)
    result["requested"] = requested
    result["found"] = True
    return result


def run_brain_query(request: BrainQueryRequest) -> dict[str, Any]:
    repo = _graph_repository()
    nodes = repo.all_nodes()
    if request.node_type:
        nodes = [node for node in nodes if node.node_type == request.node_type]
    if request.canonical_key:
        nodes = [node for node in nodes if node.canonical_key == request.canonical_key]
    if request.text:
        needle = request.text.casefold()
        nodes = [
            node
            for node in nodes
            if needle in node.canonical_key.casefold()
            or needle in str(getattr(node, "label", "")).casefold()
            or needle in str(getattr(node, "properties", {})).casefold()
        ]
    nodes = sorted(nodes, key=lambda item: item.kg_node_id)[: request.limit]
    node_ids = {node.kg_node_id for node in nodes}
    edges = []
    if request.edge_type and node_ids:
        edges = [
            edge
            for edge in repo.all_edges()
            if edge.edge_type == request.edge_type and edge.from_node_id in node_ids
        ][: request.limit]
    return {
        "nodes": [node.to_dict() for node in nodes],
        "edges": [edge.to_dict() for edge in edges],
        "limit": request.limit,
        "read_only": True,
    }


def _result_summary(result: dict[str, Any], index: int) -> str:
    title = result.get("title") or result.get("object_type") or f"Evidence {index}"
    excerpt = (result.get("authorized_excerpt") or "").strip().replace("\n", " ")
    if len(excerpt) > 420:
        excerpt = excerpt[:417].rstrip() + "..."
    citation = result.get("citation") or {}
    source = (
        citation.get("document_title")
        or citation.get("source_type")
        or "Orchid Continuum evidence"
    )
    verification = result.get("verification_state") or "unknown"
    return f"{index}. {title} — {source} [{verification}]" + (
        f"\n   {excerpt}" if excerpt else ""
    )


def _retrieval(
    message: str, mode: str, limit: int, internal_access: bool
) -> dict[str, Any]:
    query = RetrievalQuery(
        text=message[:500],
        mode=mode,
        limit=limit,
        per_source_limit=3,
        parent_expansion="AUTO",
        internal_access=internal_access,
    )
    return ENGINE.search(query)


def _compose_answer(
    message: str,
    retrieval: dict[str, Any],
    analysis: dict[str, Any] | None,
    dataset: dict[str, Any] | None,
    graph: dict[str, Any] | None,
    brain: dict[str, Any] | None,
) -> str:
    results = retrieval.get("results", [])
    lines = ["Calyx searched the Orchid Continuum before answering."]
    if results:
        lines.append(
            f"I found {retrieval.get('total_eligible_results', len(results))} eligible indexed evidence objects; showing the top {len(results)}."
        )
        lines.append("")
        lines.extend(
            _result_summary(item, i) for i, item in enumerate(results, start=1)
        )
    else:
        lines.append(
            "I did not find an eligible indexed evidence object for this question yet. That is a knowledge-coverage result, not evidence that the answer is absent from the external literature."
        )
    if graph is not None:
        lines.append("")
        lines.append(
            f"Knowledge Graph context: found={graph.get('found', True)}; nodes={len(graph.get('nodes', []))}; edges={len(graph.get('edges', []))}."
        )
    if brain is not None:
        lines.append("")
        lines.append(
            f"Brain graph query: nodes={len(brain.get('nodes', []))}; edges={len(brain.get('edges', []))}."
        )
    if analysis is not None:
        lines.append("")
        lines.append(
            f"Mathematical analysis: {analysis['operation']} = {analysis['result']}"
        )
    if dataset is not None:
        lines.append("")
        lines.append(
            f"Dataset analysis: {dataset['operation']} over {dataset.get('row_count', 0)} rows."
        )
    lines.append("")
    lines.append("Question: " + message)
    return "\n".join(lines)


def _build_report(payload: ConversationRequest, answer: dict[str, Any]) -> str:
    retrieval = answer["retrieval"]
    out = io.StringIO()
    out.write("# Calyx Analysis Report\n\n")
    out.write(f"Conversation ID: `{answer['conversation_id']}`\n\n")
    out.write(f"Persistence: `{answer['persistence_mode']}`\n\n")
    out.write("## Question\n\n")
    out.write(payload.message + "\n\n")
    out.write("## Calyx response\n\n")
    out.write(answer["answer"] + "\n\n")
    if answer.get("analysis") is not None:
        out.write("## Mathematical analysis\n\n")
        out.write("```json\n" + repr(answer["analysis"]) + "\n```\n\n")
    if answer.get("dataset_analysis") is not None:
        out.write("## Dataset analysis\n\n")
        out.write("```json\n" + repr(answer["dataset_analysis"]) + "\n```\n\n")
    if answer.get("knowledge_graph") is not None:
        out.write("## Knowledge Graph context\n\n")
        out.write("```json\n" + repr(answer["knowledge_graph"]) + "\n```\n\n")
    if answer.get("brain") is not None:
        out.write("## Brain query\n\n")
        out.write("```json\n" + repr(answer["brain"]) + "\n```\n\n")
    out.write("## Evidence ledger\n\n")
    for i, result in enumerate(retrieval.get("results", []), start=1):
        citation = result.get("citation") or {}
        out.write(
            f"### {i}. {result.get('title') or result.get('object_type') or 'Evidence'}\n\n"
        )
        out.write(f"- Object type: {result.get('object_type')}\n")
        out.write(f"- Verification: {result.get('verification_state')}\n")
        out.write(f"- Review state: {result.get('review_state')}\n")
        out.write(f"- Ranking score: {result.get('fused_score')}\n")
        out.write(
            f"- Source: {citation.get('document_title') or citation.get('source_type')}\n"
        )
        out.write(f"- Locator: {citation.get('locator')}\n")
        out.write(f"- Revision: {citation.get('revision_id')}\n\n")
    out.write("## Retrieval diagnostics\n\n")
    out.write(f"- Mode: {retrieval.get('retrieval_mode')}\n")
    out.write(f"- Eligible results: {retrieval.get('total_eligible_results')}\n")
    out.write(f"- Deduplicated: {retrieval.get('deduplicated_count')}\n")
    out.write(f"- Ranking version: {retrieval.get('ranking_configuration_version')}\n")
    out.write(f"- Elapsed ms: {retrieval.get('elapsed_ms')}\n")
    out.write("\n## Governance\n\n")
    out.write(
        "This report is an analytical artifact. Conversation and analysis do not automatically publish scientific claims or mutate canonical Knowledge Graph state.\n"
    )
    return out.getvalue()


def _execute(payload: ConversationRequest) -> dict[str, Any]:
    title = " ".join(payload.message.split())[:120]
    conversation_id = STORE.create_or_touch(
        payload.conversation_id, title=title, context=payload.context
    )
    history = STORE.history_text(conversation_id) if payload.include_history else ""
    operator_message = STORE.append(
        conversation_id, "operator", payload.message, {"context": payload.context}
    )
    try:
        retrieval = _retrieval(
            payload.message,
            payload.retrieval_mode,
            payload.limit,
            payload.internal_access,
        )
        analysis = run_analysis(payload.analysis) if payload.analysis else None
        dataset = (
            run_dataset_analysis(payload.dataset_analysis)
            if payload.dataset_analysis
            else None
        )
        graph = (
            run_graph_context(payload.graph_context) if payload.graph_context else None
        )
        brain = run_brain_query(payload.brain_query) if payload.brain_query else None
    except (
        ValueError,
        TypeError,
        SyntaxError,
        ZeroDivisionError,
        OverflowError,
    ) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    answer_text = _compose_answer(
        payload.message, retrieval, analysis, dataset, graph, brain
    )
    evidence_summary = {
        "eligible_results": retrieval.get("total_eligible_results"),
        "shown_results": len(retrieval.get("results", [])),
        "ranking_version": retrieval.get("ranking_configuration_version"),
        "graph_nodes": len((graph or {}).get("nodes", [])),
        "graph_edges": len((graph or {}).get("edges", [])),
        "brain_nodes": len((brain or {}).get("nodes", [])),
    }
    calyx_message = STORE.append(
        conversation_id,
        "calyx",
        answer_text,
        {
            "evidence": evidence_summary,
            "analysis": analysis,
            "dataset_operation": (dataset or {}).get("operation"),
        },
    )
    return {
        "conversation_id": conversation_id,
        "operator_message_id": operator_message["message_id"],
        "calyx_message_id": calyx_message["message_id"],
        "answer": answer_text,
        "analysis": analysis,
        "dataset_analysis": dataset,
        "knowledge_graph": graph,
        "brain": brain,
        "retrieval": retrieval,
        "context": payload.context,
        "history_context": history,
        "persistence_mode": STORE.persistence_mode,
        "epistemic_policy": {
            "continuum_first": True,
            "generative_claims_without_evidence": False,
            "conversation_does_not_publish_knowledge": True,
            "knowledge_graph_mutation": False,
        },
    }


@router.post("/query")
def query_calyx(payload: ConversationRequest) -> dict[str, Any]:
    """Ask Calyx a question grounded in Orchid Continuum evidence and optional graph/Brain context."""
    return _execute(payload)


@router.post("/analyze")
def analyze(payload: AnalysisRequest) -> dict[str, Any]:
    """Run deterministic mathematical/statistical analysis without arbitrary code execution."""
    try:
        return run_analysis(payload)
    except (
        ValueError,
        TypeError,
        SyntaxError,
        ZeroDivisionError,
        OverflowError,
    ) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/dataset/analyze")
def analyze_dataset(payload: DatasetAnalysisRequest) -> dict[str, Any]:
    """Analyze a tabular JSON dataset with descriptive statistics or a correlation matrix."""
    try:
        return run_dataset_analysis(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/knowledge-graph")
def knowledge_graph_context(payload: GraphContextRequest) -> dict[str, Any]:
    """Read canonical Knowledge Graph context for a focal node, taxon, or genus."""
    try:
        return run_graph_context(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/brain-query")
def brain_query(payload: BrainQueryRequest) -> dict[str, Any]:
    """Read the Brain graph with explicit filters; this endpoint does not mutate knowledge."""
    try:
        return run_brain_query(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/conversations")
def recent_conversations(limit: int = Query(20, ge=1, le=100)) -> dict[str, Any]:
    return {
        "conversations": STORE.recent(limit=limit),
        "persistence_mode": STORE.persistence_mode,
    }


@router.get("/conversations/{conversation_id}")
def get_conversation(
    conversation_id: str, message_limit: int = Query(100, ge=1, le=500)
) -> dict[str, Any]:
    try:
        conversation = STORE.get(conversation_id, message_limit=message_limit)
    except Exception as exc:
        raise HTTPException(
            status_code=422, detail="invalid conversation identifier"
        ) from exc
    if conversation is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    conversation["persistence_mode"] = STORE.persistence_mode
    return conversation


@router.post("/report", response_class=PlainTextResponse)
def report(payload: ConversationRequest) -> PlainTextResponse:
    """Generate a downloadable Markdown analysis report with evidence and provenance."""
    answer = _execute(payload)
    content = _build_report(payload, answer)
    filename = f"calyx-report-{answer['conversation_id']}.md"
    return PlainTextResponse(
        content,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/capabilities")
def capabilities() -> dict[str, Any]:
    return {
        "status": "operational",
        "interface": "Calyx Conversational Analysis Phase 2",
        "endpoints": [
            "/api/calyx/query",
            "/api/calyx/analyze",
            "/api/calyx/dataset/analyze",
            "/api/calyx/knowledge-graph",
            "/api/calyx/brain-query",
            "/api/calyx/conversations",
            "/api/calyx/report",
        ],
        "retrieval": ["LEXICAL", "SEMANTIC", "HYBRID"],
        "analysis": [
            "expression",
            "summary",
            "correlation",
            "covariance",
            "linear_regression",
            "percent_change",
            "confidence_interval_mean",
            "moving_average",
        ],
        "analysis_method_notes": {
            "confidence_interval_mean": {
                "status": "approximation_only",
                "canonical_scientific_method": False,
                "distribution": "normal",
                "governed_research_equivalent": "CALYX-617 Student-t mean confidence interval (pending activation)",
            }
        },
        "dataset_analysis": ["describe", "correlation_matrix"],
        "knowledge_sources": ["evidence_index", "knowledge_graph", "brain_graph"],
        "conversation_persistence": STORE.persistence_mode,
        "reports": ["markdown-download"],
        "continuum_first": True,
        "publication_boundary": "read/analyze only; no automatic scientific publication or graph mutation",
    }
