# Calyx Backend

Backend API for Calyx - Orchid Show Management System powered by Orchid Continuum.

## Overview
- Purpose: API backend for orchid show operations, entries, volunteers, and judging
- Stack: Python 3.11, FastAPI, SQLAlchemy, Alembic
- Database: SQLite (development) or PostgreSQL (production via DATABASE_URL)
- Frontend: Famous AI (separate project)

## Recent Changes
- 2026-01-28: Restructured with new routers, models, configurable CORS, API key auth

## Environment Variables
- `DATABASE_URL` - PostgreSQL connection (default: sqlite:///./calyx.db)
- `PORT` - Server port (default: 3000)
- `CORS_ALLOW_ORIGINS` - Comma-separated origins or `*` (default: `*`)
- `CALYX_API_KEY` - Optional API key for authentication
- `AUTO_CREATE_TABLES` - Set to `1` to auto-create tables (default: `1`)

## Project Structure
```
app/
  main.py           - FastAPI app entry point
  database.py       - Database configuration (lazy init)
  models.py         - SQLAlchemy models (Show, Entry, VolunteerTask, Award)
  schemas.py        - Pydantic schemas
  deps.py           - Dependencies
  security.py       - API key authentication
  routers/
    health.py       - Health check endpoint
    tiles.py        - Tile registry for frontend
    shows.py        - Shows CRUD
    entries.py      - Entries CRUD
    volunteers.py   - Volunteer tasks CRUD
    awards.py       - Awards CRUD
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

## User Preferences
- Do NOT build UI
- Do NOT invent judging rules
- Focus on correctness, clarity, stability
