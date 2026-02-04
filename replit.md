# Calyx Backend

Backend API for Calyx - Orchid Show Management System powered by Orchid Continuum.

## Overview
- Purpose: API backend for orchid show operations, entries, volunteers, and judging
- Stack: Python 3.11, FastAPI, SQLAlchemy, Alembic
- Database: SQLite (development) or PostgreSQL (production via DATABASE_URL)
- Frontend: Famous AI (separate project)

## Recent Changes
- 2026-02-04: Added Judging module (judges, score_submissions, show locking)
- 2026-02-04: Added System Reference Documents feature for AOS judging PDFs
- 2026-01-28: Restructured with new routers, models, configurable CORS, API key auth

## Environment Variables
- `DATABASE_URL` - PostgreSQL connection (default: sqlite:///./calyx.db)
- `PORT` - Server port (default: 3000)
- `CORS_ALLOW_ORIGINS` - Comma-separated origins or `*` (default: `*`)
- `CALYX_API_KEY` - Optional API key for authentication
- `ADMIN_API_KEY` - Optional API key for admin endpoints (reference doc uploads)
- `AUTO_CREATE_TABLES` - Set to `1` to auto-create tables (default: `1`)
- `REFERENCE_DOCS_DIR` - Storage path for reference documents (default: /home/runner/workspace/data/reference_docs)

## Project Structure
```
app/
  main.py           - FastAPI app entry point
  database.py       - Database configuration (lazy init)
  models.py         - SQLAlchemy models
  schemas.py        - Pydantic schemas
  storage.py        - File storage utility with SHA256 hashing
  deps.py           - Dependencies
  security.py       - API key authentication
  routers/
    health.py          - Health check endpoint
    tiles.py           - Tile registry for frontend
    shows.py           - Shows CRUD
    entries.py         - Entries CRUD
    volunteers.py      - Volunteer tasks CRUD
    awards.py          - Awards CRUD
    calyx_core.py      - Organizations, contacts, events, templates
    reference_docs.py  - System reference documents (AOS PDFs)
    judging.py         - Judges and score submissions
```

## Run Command
```
uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-3000}
```

## API Endpoints
- `GET /health` - Health check
- `GET /docs` - Swagger UI
- `GET /api/tiles/registry` - Tile registry for frontend
- `GET/POST /api/shows` - Shows
- `GET/POST /api/entries` - Entries
- `GET/POST /api/volunteer-tasks` - Volunteer tasks
- `GET/POST /api/awards` - Awards

### Reference Documents (AOS Judging PDFs)
- `GET /api/reference-docs` - List active documents
- `GET /api/reference-docs/{id}` - Get document metadata
- `GET /api/reference-docs/{id}/download` - Download PDF
- `POST /api/admin/reference-docs` - Upload document (multipart/form-data)
- `PATCH /api/admin/reference-docs/{id}` - Update is_active/notes

Document types: AOS_JUDGING_SCORE_SHEET, AOS_JUDGING_ENTRY_FORM, AOS_AWARDS_CRITERIA_CCM_CCE_AQ, AOS_JUDGES_STYLE_BOOK, OTHER_REFERENCE

### Judging Module
- `POST /api/judges` - Register a judge for a show
- `GET /api/judges?show_id=` - List judges for a show
- `POST /api/score-submissions` - Submit score (rejects if show locked or duplicate)
- `GET /api/entries/{entry_id}/scores` - Get all scores for an entry

Shows have `judging_locked` boolean - when true, score submissions are rejected (HTTP 409).

## User Preferences
- Do NOT build UI
- Do NOT invent judging rules
- Focus on correctness, clarity, stability
