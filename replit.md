# Orchid Judge Backend

FastAPI backend for Orchid Continuum's orchid judging application.

## Overview
- Purpose: API backend for orchid show judging system
- Stack: Python 3.11, FastAPI, SQLAlchemy
- Database: SQLite (development) or PostgreSQL (production via DATABASE_URL)

## Recent Changes
- 2026-01-28: Initial Replit setup with CORS and health endpoint

## Project Structure
- `app/` - Main application code
  - `main.py` - FastAPI app entry point
  - `database.py` - Database configuration
  - `api/` - API routes
  - `models/` - SQLAlchemy models
  - `tiles/` - Tile registry

## Running
The app runs via uvicorn on port 3000:
```
uvicorn app.main:app --host 0.0.0.0 --port 3000
```

## API Endpoints
- `GET /health` - Health check
- `GET /api/tiles/registry` - Tile registry
