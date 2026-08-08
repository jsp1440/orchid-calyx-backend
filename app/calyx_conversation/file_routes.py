from __future__ import annotations

import io
import re
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse

from app.security import verify_owner_or_api_key

from .file_analysis import chart_spec, parse_tabular_file

router = APIRouter(
    prefix="/calyx/dataset",
    tags=["calyx-file-analysis"],
    dependencies=[Depends(verify_owner_or_api_key)],
)

FileUpload = Annotated[UploadFile, File()]
AnalysisOperation = Annotated[Literal["describe", "correlation_matrix"], Form()]
OptionalSheet = Annotated[str | None, Form()]
OptionalChart = Annotated[Literal["scatter", "line", "bar", "histogram"] | None, Form()]
OptionalAxis = Annotated[str | None, Form()]
PreviewRows = Annotated[int, Form(ge=1, le=100)]


def _run_uploaded_analysis(parsed: dict, operation: str) -> dict:
    from .routes import DatasetAnalysisRequest, run_dataset_analysis

    return run_dataset_analysis(
        DatasetAnalysisRequest(operation=operation, columns=parsed["columns"])
    )


def _file_summary(parsed: dict) -> dict:
    return {
        "filename": parsed["filename"],
        "row_count": parsed["row_count"],
        "column_count": parsed["column_count"],
        "column_names": list(parsed["columns"]),
        "metadata": parsed["metadata"],
    }


def _analysis_markdown(parsed: dict, analysis: dict, spec: dict | None) -> str:
    out = io.StringIO()
    out.write("# Calyx Dataset Analysis Report\n\n")
    out.write(f"Source file: `{parsed['filename']}`\n\n")
    out.write(f"Rows: {parsed['row_count']}  \nColumns: {parsed['column_count']}\n\n")
    if parsed["metadata"].get("sheet"):
        out.write(f"Worksheet: `{parsed['metadata']['sheet']}`\n\n")
    out.write("## Analysis\n\n")
    out.write(f"Operation: `{analysis['operation']}`\n\n")
    if analysis["operation"] == "describe":
        for name, summary in analysis["columns"].items():
            out.write(f"### {name}\n\n")
            for key, value in summary.items():
                out.write(f"- {key}: {value}\n")
            out.write("\n")
    else:
        out.write("### Correlation matrix\n\n")
        for left, row in analysis["matrix"].items():
            out.write(f"- {left}: {row}\n")
        out.write("\n")
    if spec is not None:
        out.write("## Chart specification\n\n")
        out.write(f"- Type: {spec['chart_type']}\n")
        out.write(f"- X: {spec.get('x')}\n")
        out.write(f"- Y: {spec.get('y')}\n")
        out.write(f"- Points returned: {spec['points_returned']}\n")
        out.write(f"- Truncated: {spec['truncated']}\n\n")
    out.write("## Governance\n\n")
    out.write("The uploaded file was analyzed in memory and was not persisted by this endpoint. The report does not publish scientific claims or mutate canonical Orchid Continuum knowledge.\n")
    return out.getvalue()


def _report_filename(source_filename: str) -> str:
    stem = source_filename.rsplit(".", 1)[0] or "dataset"
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-._") or "dataset"
    return f"calyx-{safe_stem[:80]}-analysis.md"


@router.post("/upload-analyze")
async def upload_analyze(
    file: FileUpload,
    operation: AnalysisOperation = "describe",
    sheet_name: OptionalSheet = None,
    chart_type: OptionalChart = None,
    x: OptionalAxis = None,
    y: OptionalAxis = None,
) -> dict:
    """Upload CSV/XLSX, run deterministic analysis, and optionally return a chart spec."""
    try:
        content = await file.read()
        parsed = parse_tabular_file(content, file.filename or "upload", sheet_name=sheet_name)
        analysis = _run_uploaded_analysis(parsed, operation)
        spec = (
            chart_spec(parsed["columns"], chart_type=chart_type, x=x, y=y)
            if chart_type
            else None
        )
        return {
            "file": _file_summary(parsed),
            "analysis": analysis,
            "chart_spec": spec,
            "governance": {
                "read_only": True,
                "file_persisted": False,
                "knowledge_graph_mutation": False,
            },
        }
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        await file.close()


@router.post("/upload-report", response_class=PlainTextResponse)
async def upload_report(
    file: FileUpload,
    operation: AnalysisOperation = "describe",
    sheet_name: OptionalSheet = None,
    chart_type: OptionalChart = None,
    x: OptionalAxis = None,
    y: OptionalAxis = None,
) -> PlainTextResponse:
    """Analyze an uploaded dataset and return a downloadable evidence-safe Markdown report."""
    try:
        content = await file.read()
        parsed = parse_tabular_file(content, file.filename or "upload", sheet_name=sheet_name)
        analysis = _run_uploaded_analysis(parsed, operation)
        spec = (
            chart_spec(parsed["columns"], chart_type=chart_type, x=x, y=y)
            if chart_type
            else None
        )
        report = _analysis_markdown(parsed, analysis, spec)
        return PlainTextResponse(
            report,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{_report_filename(parsed["filename"])}"'},
        )
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        await file.close()


@router.post("/upload-preview")
async def upload_preview(
    file: FileUpload,
    sheet_name: OptionalSheet = None,
    preview_rows: PreviewRows = 20,
) -> dict:
    """Inspect a CSV/XLSX schema and a bounded row preview without persisting the file."""
    try:
        content = await file.read()
        parsed = parse_tabular_file(content, file.filename or "upload", sheet_name=sheet_name)
        names = list(parsed["columns"])
        rows = []
        for index in range(min(preview_rows, parsed["row_count"])):
            rows.append({name: parsed["columns"][name][index] for name in names})
        return {
            "filename": parsed["filename"],
            "row_count": parsed["row_count"],
            "column_count": parsed["column_count"],
            "columns": names,
            "metadata": parsed["metadata"],
            "preview": rows,
            "file_persisted": False,
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        await file.close()
