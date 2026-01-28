# Calyx Backend

Backend API for Calyx - Orchid Show Management System by Orchid Continuum.

## Overview
- Purpose: API backend for orchid show operations, entries, volunteers, and judging
- Stack: Python 3.11, FastAPI, SQLAlchemy
- Database: SQLite (development) or PostgreSQL (production via DATABASE_URL)
- Frontend: Famous AI (separate project)

## Recent Changes
- 2026-01-28: Initial Replit setup with CORS, health endpoint, lazy DB init

## Project Structure
- `app/` - Main application code
  - `main.py` - FastAPI app entry point
  - `database.py` - Database configuration (lazy initialization)
  - `api/` - API routes
  - `models/` - SQLAlchemy models
  - `tiles/` - Tile registry for UI navigation

## Running
```
uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-3000}
```

## API Endpoints
- `GET /health` - Health check
- `GET /api/tiles/registry` - Tile registry for frontend navigation
- `GET /api/orgs` - List organizations
- `POST /api/orgs` - Create organization
- `GET /api/orgs/{org_id}/shows` - List shows for an org
- `POST /api/orgs/{org_id}/shows` - Create show
- `GET /api/shows/{show_id}/zones` - List zones
- `GET /api/shows/{show_id}/vendors` - List vendors
- `GET /api/shows/{show_id}/volunteer-roles` - List volunteer roles
- `GET /api/shows/{show_id}/volunteer-shifts` - List shifts
- `POST /api/public/shifts/{shift_id}/signup` - Public volunteer signup
