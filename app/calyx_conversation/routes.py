from __future__ import annotations

import ast
import io
import math
import statistics
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from app.evidence_retrieval.engine import RetrievalEngine
from app.evidence_retrieval.models import RetrievalQuery
from app.evidence_retrieval.routes import REPO
from app.evidence_retrieval.provider import DeterministicLocalProvider
from app.security import verify_owner_or_api_key

router = APIRouter(
    prefix="/calyx",
    tags=["calyx-conversation"],
    dependencies=[Depends(verify_owner_or_api_key)],
)

ENGINE = RetrievalEngine(REPO, DeterministicLocalProvider())


class AnalysisRequest(BaseModel):
    operation: Literal[
        "expression",
        "summary",
        "correlation",
        "linear_regression",
        "percent_change",
    ]
    expression: str | None = None
    values: list[float] = Field(default_factory=list, max_length=100000)
    x: list[float] = Field(default_factory=list, max_length=100000)
    y: list[float] = Field(default_factory=list, max_length=100000)


class ConversationRequest(BaseModel):
    message: str = Field(min_length=1, max_length=5000)
    conversation_id: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    analysis: AnalysisRequest | None = None
    retrieval_mode: Literal["LEXICAL", "SEMANTIC", "HYBRID"] = "HYBRID"
    limit: int = Field(8, ge=1, le=25)
    internal_access: bool = True


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
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.Name) and node.id in _ALLOWED_CONSTS:
        return float(_ALLOWED_CONSTS[node.id])
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
        return float(_ALLOWED_BINOPS[type(node.op)](_eval_math(node.left), _eval_math(node.right)))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARY:
        return float(_ALLOWED_UNARY[type(node.op)](_eval_math(node.operand)))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _ALLOWED_FUNCS:
        if node.keywords:
            raise ValueError("keyword arguments are not supported")
        return float(_ALLOWED_FUNCS[node.func.id](*[_eval_math(arg) for arg in node.args]))
    raise ValueError("unsupported mathematical expression")


def safe_expression(expression: str) -> float:
    if len(expression) > 500:
        raise ValueError("expression too long")
    tree = ast.parse(expression, mode="eval")
    for node in ast.walk(tree):
        if isinstance(node, (ast.Attribute, ast.Subscript, ast.Lambda, ast.Dict, ast.ListComp, ast.GeneratorExp)):
            raise ValueError("unsupported mathematical expression")
    return _eval_math(tree)


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
        result: dict[str, Any] = {
            "count": len(values),
            "sum": sum(values),
            "mean": statistics.fmean(values),
            "median": statistics.median(values),
            "min": min(values),
            "max": max(values),
        }
        if len(values) > 1:
            result["stdev_sample"] = statistics.stdev(values)
            result["variance_sample"] = statistics.variance(values)
        return {"operation": op, "result": result}

    if op in {"correlation", "linear_regression"}:
        if len(request.x) != len(request.y) or len(request.x) < 2:
            raise ValueError("x and y must have the same length and at least two observations")
        mean_x = statistics.fmean(request.x)
        mean_y = statistics.fmean(request.y)
        sxx = sum((v - mean_x) ** 2 for v in request.x)
        syy = sum((v - mean_y) ** 2 for v in request.y)
        sxy = sum((a - mean_x) * (b - mean_y) for a, b in zip(request.x, request.y))
        if sxx == 0:
            raise ValueError("x has zero variance")
        if op == "correlation":
            if syy == 0:
                raise ValueError("y has zero variance")
            return {"operation": op, "result": sxy / math.sqrt(sxx * syy), "n": len(request.x)}
        slope = sxy / sxx
        intercept = mean_y - slope * mean_x
        r_squared = (sxy * sxy) / (sxx * syy) if syy else 1.0
        return {
            "operation": op,
            "result": {"slope": slope, "intercept": intercept, "r_squared": r_squared, "n": len(request.x)},
        }

    if op == "percent_change":
        if len(request.values) != 2:
            raise ValueError("percent_change requires exactly two values: old, new")
        old, new = request.values
        if old == 0:
            raise ValueError("old value cannot be zero")
        return {"operation": op, "result": ((new - old) / old) * 100.0, "old": old, "new": new}

    raise ValueError("unsupported analysis operation")


def _result_summary(result: dict[str, Any], index: int) -> str:
    title = result.get("title") or result.get("object_type") or f"Evidence {index}"
    excerpt = (result.get("authorized_excerpt") or "").strip().replace("\n", " ")
    if len(excerpt) > 420:
        excerpt = excerpt[:417].rstrip() + "..."
    citation = result.get("citation") or {}
    source = citation.get("document_title") or citation.get("source_type") or "Orchid Continuum evidence"
    verification = result.get("verification_state") or "unknown"
    return f"{index}. {title} — {source} [{verification}]" + (f"\n   {excerpt}" if excerpt else "")


def _retrieval(message: str, mode: str, limit: int, internal_access: bool) -> dict[str, Any]:
    query = RetrievalQuery(
        text=message[:500],
        mode=mode,
        limit=limit,
        per_source_limit=3,
        parent_expansion="AUTO",
        internal_access=internal_access,
    )
    return ENGINE.search(query)


def _compose_answer(message: str, retrieval: dict[str, Any], analysis: dict[str, Any] | None) -> str:
    results = retrieval.get("results", [])
    lines = ["Calyx searched the Orchid Continuum before answering."]
    if results:
        lines.append(f"I found {retrieval.get('total_eligible_results', len(results))} eligible evidence objects; showing the top {len(results)}.")
        lines.append("")
        lines.extend(_result_summary(item, i) for i, item in enumerate(results, start=1))
    else:
        lines.append("I did not find an eligible indexed evidence object for this question yet. That is a knowledge-coverage result, not evidence that the answer is unknown in the external literature.")
    if analysis is not None:
        lines.append("")
        lines.append(f"Mathematical analysis: {analysis['operation']} = {analysis['result']}")
    lines.append("")
    lines.append("Question: " + message)
    return "\n".join(lines)


def _build_report(payload: ConversationRequest, answer: dict[str, Any]) -> str:
    now = datetime.now(timezone.utc).isoformat()
    retrieval = answer["retrieval"]
    out = io.StringIO()
    out.write("# Calyx Analysis Report\n\n")
    out.write(f"Generated: {now}\n\n")
    out.write(f"Conversation ID: `{answer['conversation_id']}`\n\n")
    out.write("## Question\n\n")
    out.write(payload.message + "\n\n")
    out.write("## Calyx response\n\n")
    out.write(answer["answer"] + "\n\n")
    if answer.get("analysis") is not None:
        out.write("## Mathematical analysis\n\n")
        out.write("```json\n" + str(answer["analysis"]) + "\n```\n\n")
    out.write("## Evidence ledger\n\n")
    for i, result in enumerate(retrieval.get("results", []), start=1):
        citation = result.get("citation") or {}
        out.write(f"### {i}. {result.get('title') or result.get('object_type') or 'Evidence'}\n\n")
        out.write(f"- Object type: {result.get('object_type')}\n")
        out.write(f"- Verification: {result.get('verification_state')}\n")
        out.write(f"- Review state: {result.get('review_state')}\n")
        out.write(f"- Ranking score: {result.get('fused_score')}\n")
        out.write(f"- Source: {citation.get('document_title') or citation.get('source_type')}\n")
        out.write(f"- Locator: {citation.get('locator')}\n")
        out.write(f"- Revision: {citation.get('revision_id')}\n\n")
    out.write("## Retrieval diagnostics\n\n")
    out.write(f"- Mode: {retrieval.get('retrieval_mode')}\n")
    out.write(f"- Eligible results: {retrieval.get('total_eligible_results')}\n")
    out.write(f"- Deduplicated: {retrieval.get('deduplicated_count')}\n")
    out.write(f"- Ranking version: {retrieval.get('ranking_configuration_version')}\n")
    out.write(f"- Elapsed ms: {retrieval.get('elapsed_ms')}\n")
    return out.getvalue()


def _execute(payload: ConversationRequest) -> dict[str, Any]:
    conversation_id = payload.conversation_id or str(uuid.uuid4())
    try:
        retrieval = _retrieval(payload.message, payload.retrieval_mode, payload.limit, payload.internal_access)
        analysis = run_analysis(payload.analysis) if payload.analysis else None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    answer_text = _compose_answer(payload.message, retrieval, analysis)
    return {
        "conversation_id": conversation_id,
        "answer": answer_text,
        "analysis": analysis,
        "retrieval": retrieval,
        "context": payload.context,
        "epistemic_policy": {
            "continuum_first": True,
            "generative_claims_without_evidence": False,
            "conversation_does_not_publish_knowledge": True,
        },
    }


@router.post("/query")
def query_calyx(payload: ConversationRequest) -> dict[str, Any]:
    """Ask Calyx a question grounded in indexed Orchid Continuum evidence."""
    return _execute(payload)


@router.post("/analyze")
def analyze(payload: AnalysisRequest) -> dict[str, Any]:
    """Run deterministic mathematical/statistical analysis without arbitrary code execution."""
    try:
        return run_analysis(payload)
    except (ValueError, SyntaxError, ZeroDivisionError, OverflowError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/report", response_class=PlainTextResponse)
def report(payload: ConversationRequest) -> PlainTextResponse:
    """Generate a downloadable Markdown analysis report with evidence ledger."""
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
        "interface": "Calyx Conversational Analysis MVP",
        "endpoints": ["/api/calyx/query", "/api/calyx/analyze", "/api/calyx/report"],
        "retrieval": ["LEXICAL", "SEMANTIC", "HYBRID"],
        "analysis": ["expression", "summary", "correlation", "linear_regression", "percent_change"],
        "reports": ["markdown-download"],
        "continuum_first": True,
        "publication_boundary": "read/analyze only; no automatic scientific publication",
    }
