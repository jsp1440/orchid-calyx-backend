# BUILD-612 — Calyx File Analysis

Date: 2026-08-08
Status: implemented on branch; validation required before merge

## Purpose

Remove the manual JSON-conversion barrier from Calyx quantitative analysis. An authenticated operator should be able to give Calyx the same kinds of tabular files used with Julius-style analysis workflows and receive immediate, deterministic analysis and a downloadable report.

## Implemented

1. Added bounded in-memory CSV and XLSX ingestion with a 10 MB upload limit, 100,000-row limit, and 500-column limit.
2. Added UTF-8 CSV handling with automatic scalar normalization for integers, finite floats, booleans, blanks, and text so CSV and XLSX numeric data behave consistently.
3. Added XLSX worksheet selection using read-only/data-only workbook loading; uploaded workbooks are never modified.
4. Added duplicate and blank header normalization so uploaded tables remain addressable without silently dropping columns.
5. Added authenticated `POST /api/calyx/dataset/upload-preview` for schema inspection and a bounded row preview without persistence.
6. Added authenticated `POST /api/calyx/dataset/upload-analyze` for direct descriptive-statistics and correlation-matrix analysis from CSV/XLSX.
7. Added optional chart specifications for line, scatter, bar, and histogram visualizations, with inline bounded data (maximum 5,000 points) and explicit truncation metadata for frontend rendering.
8. Added authenticated `POST /api/calyx/dataset/upload-report` returning a downloadable Markdown analysis report.
9. Kept uploads ephemeral: these endpoints do not persist the uploaded file, mutate the Knowledge Graph, or publish scientific claims.
10. Expanded the dedicated Calyx validation workflow to compile, test, lint, and route-check the file-analysis surface alongside the conversation engine.
11. Added focused CSV/XLSX ingestion, type-normalization, analysis-integration, and chart-spec regression tests.

## Governance boundary

BUILD-612 performs transient read/analyze operations on operator-supplied files. It deliberately does not ingest those files into the canonical literature system, Brain, semantic index, or Knowledge Graph. Persisting an uploaded dataset or promoting its findings remains a separate governed action.

## User impact

Calyx can now accept ordinary CSV or Excel data directly instead of requiring the operator to manually rewrite the dataset into API JSON. This closes one of the largest practical gaps between the current Calyx analysis layer and the interactive data-analysis workflow expected from tools such as Julius AI.

## Next priorities after validation

- natural-language analysis planning so Calyx can infer the requested operation and axes from the user's question;
- frontend chart rendering from the returned chart specification;
- richer statistical methods and grouped/pivot-style summaries;
- durable, explicitly governed attachment/session datasets for multi-turn analysis;
- model-backed narrative synthesis constrained by calculated results and retrieved Orchid Continuum evidence.
