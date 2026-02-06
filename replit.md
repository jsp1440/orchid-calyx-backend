# Calyx Backend

Backend API for Calyx - Orchid Show Management System powered by Orchid Continuum.

## Overview
- Purpose: API backend for orchid show operations, entries, volunteers, and judging
- Stack: Python 3.11, FastAPI, SQLAlchemy
- Database: PostgreSQL (Replit-hosted via PGHOST) or SQLite fallback
- Frontend: Famous AI (separate project)

## Recent Changes
- 2026-02-06: Aligned volunteer module to spec: volunteer_signups (replaces assignments), volunteer_attendance (replaces checkins), shifts use date+time+slots_needed, volunteers use name+unique(show_id,email), signup approve/move/delete endpoints
- 2026-02-06: Added seed.sql with demo data (1 org, 1 show, 5 entries, 3 roles, 5 shifts, 6 volunteers, 8 signups, 3 attendance, 3 judges, 10 scores, 3 awards)
- 2026-02-06: Endpoint paths changed to /api/shows/{show_id}/volunteer/... pattern
- 2026-02-04: Added Judging module (judges, score_submissions, show locking, leaderboard)
- 2026-02-04: Added System Reference Documents feature for AOS judging PDFs
- 2026-01-28: Restructured with new routers, models, configurable CORS, API key auth

## Environment Variables
- `DATABASE_URL` - PostgreSQL connection (default: sqlite:///./calyx.db)
- `PORT` - Server port (default: 3000)
- `CORS_ALLOW_ORIGINS` - Comma-separated origins or `*` (default: `*`)
- `CALYX_API_KEY` - Optional API key for authentication
- `ADMIN_API_KEY` - Optional API key for admin endpoints (reference doc uploads)
- `AUTO_CREATE_TABLES` - Set to `1` to auto-create tables (default: `1`)
- `REFERENCE_DOCS_DIR` - Storage path for reference documents

## Project Structure
```
app/
  main.py           - FastAPI app entry point, startup schema reconciliation
  database.py       - Database configuration (Base, engine, session)
  models.py         - SQLAlchemy models (imports Base from database.py)
  schemas.py        - Pydantic request/response schemas
  storage.py        - File storage utility with SHA256 hashing
  deps.py           - Dependencies (get_db)
  security.py       - API key authentication (verify_api_key, require_admin)
  routers/
    health.py          - Health check endpoint
    tiles.py           - Tile registry for frontend
    shows.py           - Shows CRUD
    entries.py         - Entries CRUD
    volunteers.py      - Legacy volunteer tasks CRUD
    awards.py          - Awards CRUD
    calyx_core.py      - Organizations, contacts, events, templates
    reference_docs.py  - System reference documents (AOS PDFs)
    judging.py         - Judges, score submissions, leaderboard
    volunteer_ops.py   - Volunteer operations (roles, shifts, signups, attendance, export/import)
seed.sql              - Demo seed data (Postgres)
```

## Run Command
```
uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-3000}
```

## Database Models
### Core: Organization, Show, Entry, Award, Contact, MessageTemplate, MessageLog, Event, File, IntegrationConnection
### Reference: SystemReferenceDocument
### Judging: Judge, ScoreSubmission
### Volunteers: VolunteerRole, VolunteerShift, Volunteer, VolunteerSignup, VolunteerAttendance

## API Endpoints

### Core
- `GET /health` - Health check
- `GET /docs` - Swagger UI
- `GET/POST /api/shows` - Shows (includes judging_locked, public_volunteer_token)
- `GET/POST /api/entries` - Entries
- `GET/POST /api/awards` - Awards

### Reference Documents
- `GET /api/reference-docs` - List active documents
- `POST /api/admin/reference-docs` - Upload document (admin only)

### Judging
- `POST /api/judges` - Register judge
- `GET /api/judges?show_id=` - List judges
- `POST /api/score-submissions` - Submit score (rejects if locked/duplicate, 409)
- `GET /api/entries/{entry_id}/scores` - Entry scores
- `GET /api/shows/{show_id}/leaderboard` - Aggregate leaderboard

### Volunteer Operations (all require X-API-Key)
All paths under `/api/shows/{show_id}/volunteer/...`

**Roles:**
- `POST /api/shows/{show_id}/volunteer/roles` - Create role (name, description, location, training_url)
- `GET  /api/shows/{show_id}/volunteer/roles` - List roles

**Shifts:**
- `POST   /api/shows/{show_id}/volunteer/shifts` - Create shift (role_id, shift_date, start_time, end_time, slots_needed)
- `GET    /api/shows/{show_id}/volunteer/shifts` - List shifts
- `PATCH  /api/shows/{show_id}/volunteer/shifts/{shift_id}` - Update shift
- `DELETE /api/shows/{show_id}/volunteer/shifts/{shift_id}` - Delete shift

**Volunteers:**
- `POST /api/shows/{show_id}/volunteer/volunteers` - Create (name, email required; status default pending)
- `GET  /api/shows/{show_id}/volunteer/volunteers` - List all

**Signups:**
- `POST   /api/shows/{show_id}/volunteer/signups` - Create signup (shift_id, volunteer_id, signup_source)
- `GET    /api/shows/{show_id}/volunteer/signups` - List signups
- `PATCH  /api/shows/{show_id}/volunteer/signups/{id}/approve` - Approve (sets approved=true, approved_by, approved_at)
- `PATCH  /api/shows/{show_id}/volunteer/signups/{id}/move` - Move to different shift
- `DELETE /api/shows/{show_id}/volunteer/signups/{id}` - Remove signup

**Attendance:**
- `POST /api/shows/{show_id}/volunteer/attendance/check-in` - Check in (volunteer_id, shift_id, method)
- `POST /api/shows/{show_id}/volunteer/attendance/check-out` - Check out (409 if not checked in)

**Export/Import:**
- `GET  /api/shows/{show_id}/volunteer/export.csv` - CSV export
- `POST /api/shows/{show_id}/volunteer/import` - CSV import (idempotent upsert by email)
- `GET  /api/shows/{show_id}/volunteer/printable` - Printable HTML schedule

### Business Rules
- Unique constraint on (show_id, email) for volunteers — prevents duplicate profiles
- Unique constraint on (shift_id, volunteer_id) for signups — prevents duplicate signups
- Unique constraint on (shift_id, volunteer_id) for attendance — prevents duplicate check-ins
- Shift slots enforced server-side (409 if slots full)
- CSV import matches volunteers by email; creates roles/shifts/signups as needed
- Re-imports are idempotent (no duplicate data)
- Show's `public_volunteer_token` enables public signup link
- Score submissions rejected if show.judging_locked=true (409)
- Score submissions unique per (show_id, entry_id, judge_id)

## User Preferences
- Do NOT build UI
- Do NOT invent judging rules
- Do NOT restructure the project
- Focus on correctness, clarity, stability
