from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.security import verify_owner_or_api_key

from .file_analysis import chart_spec, parse_tabular_file

router = APIRouter(
    prefix="/calyx/dataset",
    tags=["calyx-file-analysis"],
    dependencies=[Depends(verify_owner_or_api_key)],
)


@router.post("/upload-analyze")
async def upload_analyze(
    file: UploadFile = File(...),
    operation: Literal["describe", "correlation_matrix"] = Form("describe"),
    sheet_name: str | None = Form(None),
    chart_type: Literal["scatter", "line", "bar", "histogram"] | None = Form(None),
    x: str | None = Form(None),
    y: str | None = Form(None),
) -> dict:
    """Upload CSV/XLSX, run deterministic analysis, and optionally return a chart spec."""
    try:
        content = await file.read()
        parsed = parse_tabular_file(content, file.filename or "upload", sheet_name=sheet_name)
        from .routes import DatasetAnalysisRequest, run_dataset_analysis

        analysis = run_dataset_analysis(
            DatasetAnalysisRequest(operation=operation, columns=parsed["columns"])
        )
        spec = (
            chart_spec(parsed["columns"], chart_type=chart_type, x=x, y=y)
            if chart_type
            else None
        )
        return {
            "file": {
                "filename": parsed["filename"],
                "row_count": parsed["row_count"],
                "column_count": parsed["column_count"],
                "column_names": list(parsed["columns"]),
                "metadata": parsed["metadata"],
            },
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


@router.post("/upload-preview")
async def upload_preview(
    file: UploadFile = File(...),
    sheet_name: str | None = Form(None),
    preview_rows: int = Form(20, ge=1, le=100),
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
