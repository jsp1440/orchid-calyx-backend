# Calyx Backend

Backend API for Calyx - Orchid Show Management System powered by Orchid Continuum.

## Overview
- Purpose: API backend for orchid show operations, entries, volunteers, and judging
- Stack: Python 3.11, FastAPI, SQLAlchemy, openpyxl
- Database: PostgreSQL (Replit-hosted via PGHOST) or SQLite fallback
- Frontend: Famous AI (separate project)

## Recent Changes
- 2026-02-06: Aligned volunteer module to design doc v2: VolunteerAssignment (replaces Signup+Attendance), Volunteer has approved(bool)/opt_in_sms/notes, VolunteerShift uses datetime start_time/end_time + capacity, VolunteerRole has default_shift_length
- 2026-02-06: Excel (xlsx) export/import with conflict detection and coordinator override
- 2026-02-06: Added Feedback endpoint (POST /api/feedback) for beta capture
- 2026-02-06: Added Judging widget stubs (GET /judging/criteria, POST /judging/evaluate, POST /judging/submit)
- 2026-02-06: Updated seed.sql for new schema (assignments, approved booleans, datetime shifts)
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
    judging.py         - Judges, score submissions, leaderboard, widget stubs
    volunteer_ops.py   - Volunteer operations (roles, shifts, assignments, Excel export/import)
    feedback.py        - Feedback capture endpoint
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
### Volunteers: VolunteerRole, VolunteerShift, Volunteer, VolunteerAssignment
### Feedback: Feedback

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

### Judging Widget (plug-in)
- `GET /api/judging/criteria` - Get scoring criteria (AOS defaults)
- `POST /api/judging/evaluate` - Preview score calculation (no persist)
- `POST /api/judging/submit` - Submit and persist score

### Feedback (beta capture)
- `POST /api/feedback` - Submit feedback (module, step, worked, confusion, suggestions)
- `GET /api/feedback?module=` - List feedback (optional module filter)

### Volunteer Operations (all require X-API-Key)
All paths under `/api/shows/{show_id}/volunteer/...`

**Roles:**
- `POST /api/shows/{show_id}/volunteer/roles` - Create role (name, description, default_shift_length)
- `GET  /api/shows/{show_id}/volunteer/roles` - List roles

**Shifts:**
- `POST   /api/shows/{show_id}/volunteer/shifts` - Create shift (role_id, start_time, end_time as datetimes, capacity)
- `GET    /api/shows/{show_id}/volunteer/shifts` - List shifts
- `PATCH  /api/shows/{show_id}/volunteer/shifts/{shift_id}` - Update shift
- `DELETE /api/shows/{show_id}/volunteer/shifts/{shift_id}` - Delete shift

**Volunteers:**
- `POST  /api/shows/{show_id}/volunteer/volunteers` - Create (name, email, phone, opt_in_sms, notes, approved)
- `GET   /api/shows/{show_id}/volunteer/volunteers` - List all
- `PATCH /api/shows/{show_id}/volunteer/volunteers/{id}` - Update volunteer

**Assignments:**
- `POST   /api/shows/{show_id}/volunteer/assignments` - Create (volunteer_id, shift_id, status)
- `GET    /api/shows/{show_id}/volunteer/assignments` - List assignments
- `PATCH  /api/shows/{show_id}/volunteer/assignments/{id}/status?status=` - Update status
- `PATCH  /api/shows/{show_id}/volunteer/assignments/{id}/move` - Move to different shift
- `DELETE /api/shows/{show_id}/volunteer/assignments/{id}` - Remove assignment

**Check-in:**
- `POST /api/shows/{show_id}/volunteer/check-in?volunteer_id=&shift_id=` - Check in (sets status=checked_in)

**Export/Import:**
- `GET  /api/shows/{show_id}/volunteer/export.xlsx` - Excel export (formatted xlsx)
- `POST /api/shows/{show_id}/volunteer/import` - Excel/CSV import (conflict detection, override_conflicts param)
- `GET  /api/shows/{show_id}/volunteer/printable` - Printable HTML schedule

### Business Rules
- Unique constraint on (show_id, email) for volunteers — prevents duplicate profiles
- Unique constraint on (shift_id, volunteer_id) for assignments — prevents duplicate assignments
- Assignment status: assigned | confirmed | checked_in | no_show
- Shift capacity enforced server-side (409 if full)
- Excel import matches volunteers by email; creates roles/shifts/assignments as needed
- Conflict detection on re-import: name/phone changes flagged unless override_conflicts=true
- Re-imports are idempotent (no duplicate data)
- Show's `public_volunteer_token` enables public signup link
- Score submissions rejected if show.judging_locked=true (409)
- Score submissions unique per (show_id, entry_id, judge_id)
- Excel is a first-class interface — export and import as xlsx

## Design Philosophy (from spec)
- No user forced to register unless necessary
- Coordinator always has override power
- System adapts to humans, not the reverse
- Excel is authoritative when uploaded
- Calm beats clever, guidance beats power

## User Preferences
- Do NOT build UI
- Do NOT invent judging rules
- Do NOT restructure the project
- Focus on correctness, clarity, stability
