# Calyx Backend

Backend API for Calyx - Orchid Show Management System powered by Orchid Continuum.

## Overview
- Purpose: API backend for orchid show operations, entries, volunteers, and judging
- Stack: Python 3.11, FastAPI, SQLAlchemy
- Database: PostgreSQL (Replit-hosted via PGHOST) or SQLite fallback
- Frontend: Famous AI (separate project)

## Recent Changes
- 2026-02-06: Full Volunteer Operations module (roles, shifts, directory, assignments, check-in/out, CSV export/import, printable schedule, public signup)
- 2026-02-06: Fixed schemas.py (was corrupted), added Base to database.py
- 2026-02-06: Added judging leaderboard endpoint
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
- `REFERENCE_DOCS_DIR` - Storage path for reference documents

## Project Structure
```
app/
  main.py           - FastAPI app entry point
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
    volunteer_ops.py   - Full volunteer operations module
```

## Run Command
```
uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-3000}
```

## Database Models
### Core: Organization, Show, Entry, Award, Contact, MessageTemplate, MessageLog, Event, File, IntegrationConnection
### Reference: SystemReferenceDocument
### Judging: Judge, ScoreSubmission
### Volunteers: Volunteer, VolunteerRole, VolunteerShift, VolunteerAssignment, VolunteerCheckin

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

### Volunteer Operations (all require X-API-Key except public signup)
**Roles:**
- `POST /api/shows/{show_id}/volunteer-roles` - Create role
- `GET /api/shows/{show_id}/volunteer-roles` - List roles
- `PATCH /api/volunteer-roles/{role_id}` - Update role
- `DELETE /api/volunteer-roles/{role_id}` - Delete role

**Shifts:**
- `POST /api/shows/{show_id}/volunteer-shifts` - Create shift
- `GET /api/shows/{show_id}/volunteer-shifts?role_id=&date=` - List shifts
- `PATCH /api/volunteer-shifts/{shift_id}` - Update shift
- `DELETE /api/volunteer-shifts/{shift_id}` - Delete shift

**Directory:**
- `POST /api/shows/{show_id}/volunteers` - Create volunteer (pending/approved)
- `GET /api/shows/{show_id}/volunteers?status=` - List volunteers
- `PATCH /api/volunteers/{volunteer_id}` - Update/approve/block

**Assignments:**
- `POST /api/volunteer-assignments` - Assign (rejects if unapproved or capacity exceeded, 409)
- `GET /api/shows/{show_id}/volunteer-assignments?shift_id=&volunteer_id=` - List
- `DELETE /api/volunteer-assignments/{assignment_id}` - Remove

**Check-in/out:**
- `POST /api/volunteer-checkin` - Check in (409 if already checked in)
- `POST /api/volunteer-checkout` - Check out (409 if not checked in)

**Export/Import:**
- `GET /api/shows/{show_id}/volunteers/export.csv` - Export CSV
- `POST /api/shows/{show_id}/volunteers/import.csv` - Import CSV (idempotent upsert)
- `GET /api/shows/{show_id}/volunteers/printable` - Printable HTML schedule

**Public Signup (no API key required):**
- `POST /api/public/volunteer-signup?token=` - Public self-registration (pending status)

### Business Rules
- Volunteers must be `approved` before assignment to shifts
- Shift capacity enforced server-side (409 if exceeded)
- Unique constraints prevent duplicate assignments and check-ins
- CSV import matches by email first, then full_name+phone
- Re-imports are idempotent (no duplicate data)
- Show's `public_volunteer_token` enables public signup link

## User Preferences
- Do NOT build UI
- Do NOT invent judging rules
- Do NOT restructure the project
- Focus on correctness, clarity, stability
