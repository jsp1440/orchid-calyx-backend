# Calyx Backend

Backend API for Calyx - Orchid Show Management System powered by Orchid Continuum.

## Overview
- Purpose: API backend for orchid show operations, entries, volunteers, and judging
- Stack: Python 3.11, FastAPI, SQLAlchemy, openpyxl, qrcode
- Database: PostgreSQL (Replit-hosted via PGHOST) or SQLite fallback
- Frontend: Famous AI (separate project)

## Recent Changes
- 2026-02-06: Judge-facing scorecard workflow: GET/PUT/POST /judge/* endpoints, autosave drafts, submit with weighted totals, audit trail, access control via X-Judge-Id header
- 2026-02-06: Admin generate-scorecards endpoint (idempotent), judge assignments (event+category), published_at/closed_at timestamps on judging events
- 2026-02-06: Extended models: JudgeAssignment, Scorecard, ScorecardAuditLog; added scoring_type/min_value/max_value/choices_json to criteria, value_rank/updated_at to scores
- 2026-02-06: Expanded judging system: JudgingEvent, PlantCategory, JudgingCriterion, Exhibitor, Plant, Score (per-criterion), QR codes, event lifecycle (draft/published/closed), weighted results
- 2026-02-06: Aligned volunteer module to design doc v2: VolunteerAssignment (replaces Signup+Attendance), Volunteer has approved(bool)/opt_in_sms/notes, VolunteerShift uses datetime start_time/end_time + capacity, VolunteerRole has default_shift_length
- 2026-02-06: Excel (xlsx) export/import with conflict detection and coordinator override
- 2026-02-06: Added Feedback endpoint (POST /api/feedback) for beta capture
- 2026-02-06: Added Judging widget stubs (GET /judging/criteria, POST /judging/evaluate, POST /judging/submit)
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
  security.py       - API key authentication (verify_api_key, require_admin, require_judge)
  routers/
    health.py          - Health check endpoint
    tiles.py           - Tile registry for frontend
    shows.py           - Shows CRUD
    entries.py         - Entries CRUD
    volunteers.py      - Legacy volunteer tasks CRUD
    awards.py          - Awards CRUD
    calyx_core.py      - Organizations, contacts, events, templates
    reference_docs.py  - System reference documents (AOS PDFs)
    judging.py         - Expanded judging system + legacy score submissions + widget stubs
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
### Judging (expanded): JudgingEvent, PlantCategory, JudgingCriterion, Exhibitor, Plant, Judge, Score, JudgeAssignment, Scorecard, ScorecardAuditLog
### Judging (legacy): ScoreSubmission
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

### Judging System (expanded)

**Judging Events:**
- `POST /api/shows/{show_id}/judging/events` - Create judging event (name, judging_type, is_blind)
- `GET  /api/shows/{show_id}/judging/events` - List events for show
- `GET  /api/judging/events/{event_id}` - Get single event
- `PATCH /api/judging/events/{event_id}` - Update event
- `POST /api/judging/events/{event_id}/publish` - Publish event (enable judge access)
- `POST /api/judging/events/{event_id}/close` - Close event (freeze edits)

**Plant Categories:**
- `POST /api/judging/events/{event_id}/categories` - Create category
- `GET  /api/judging/events/{event_id}/categories` - List categories

**Judging Criteria:**
- `POST /api/judging/categories/{category_id}/criteria` - Create criterion (label, weight, max_points)
- `GET  /api/judging/categories/{category_id}/criteria` - List criteria

**Exhibitors:**
- `POST /api/exhibitors` - Create exhibitor (name, email, phone)
- `GET  /api/exhibitors` - List all exhibitors
- `GET  /api/exhibitors/{id}` - Get exhibitor

**Plants:**
- `POST /api/judging/events/{event_id}/plants` - Register plant (auto QR code)
- `GET  /api/judging/events/{event_id}/plants` - List plants (optional ?category_id= filter)
- `GET  /api/judging/plants/{plant_id}` - Get single plant

**Per-Criterion Scoring:**
- `POST /api/judging/plants/{plant_id}/scores/{judge_id}` - Submit/update scores (batch, per criterion)
- `GET  /api/judging/plants/{plant_id}/scores` - Get all scores (optional ?judge_id= filter)

**Judge Assignments (admin):**
- `POST /api/judging/events/{event_id}/assignments` - Assign judge to event (judge_id, category_id, active)
- `GET  /api/judging/events/{event_id}/assignments` - List assignments for event

**Results:**
- `GET /api/judging/events/{event_id}/results` - Weighted leaderboard with per-judge breakdowns

**Admin Utilities:**
- `POST /api/admin/judging_events/{event_id}/generate_scorecards` - Generate scorecards for all assigned judges x plants (idempotent)

### Judge-Facing Workflow (require X-Judge-Id header)
- `GET  /api/judge/me` - Get current judge profile
- `GET  /api/judge/events` - List events assigned to current judge
- `GET  /api/judge/events/{event_id}/scorecards` - List scorecards for judge in event
- `GET  /api/judge/scorecards/{scorecard_id}` - Get single scorecard (access-controlled)
- `PUT  /api/judge/scorecards/{scorecard_id}` - Autosave draft (upsert Score rows, audit log)
- `POST /api/judge/scorecards/{scorecard_id}/submit` - Submit scorecard (locks, computes weighted total, audit log)
- `GET  /api/judge/scorecards/{scorecard_id}/audit` - View audit trail for scorecard

### Judges
- `POST /api/judges` - Register judge (name, email, role)
- `GET /api/judges?show_id=` - List judges

### Legacy Score Submissions
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
- Unique constraint on (plant_id, judge_id, criterion_id) for per-criterion scores
- Unique constraint on (judging_event_id, judge_id, category_id) for judge assignments
- Unique constraint on (judging_event_id, plant_id, judge_id) for scorecards
- Assignment status: assigned | confirmed | checked_in | no_show
- Judging event status: draft | published | closed
- Scorecard status: draft | submitted
- Shift capacity enforced server-side (409 if full)
- Per-criterion scores allow revision (upsert) while event is not closed AND scorecard not submitted
- Closed judging events freeze all score edits (409)
- Submitted scorecards freeze edits (409) — no reopen endpoint yet
- QR code auto-generated per plant on creation
- Weighted scoring: criteria weights applied to results aggregation and scorecard totals
- Supports numeric scoring, ranking, and simple vote via value/choice/value_rank fields
- Score submissions rejected if show.judging_locked=true (409)
- Score submissions unique per (show_id, entry_id, judge_id)
- Excel is a first-class interface — export and import as xlsx
- Judge authentication via X-Judge-Id header (require_judge dependency)
- Scorecard access control: judges can only see/edit their own scorecards
- Audit trail: every autosave and submit action logged in scorecard_audit_log with diff_json
- Generate scorecards is idempotent — skips existing (event_id, plant_id, judge_id) combos

### Schema Management
- No Alembic migrations — schema managed via Base.metadata.create_all() + _safe_add_column() at startup
- Alembic is installed/scaffolded but alembic/versions/ is empty (not actively used)
- New columns on existing tables added via _safe_add_column() in main.py _reconcile_schema()
- New tables auto-created by SQLAlchemy create_all()

## Design Philosophy (from spec)
- No user forced to register unless necessary
- Coordinator always has override power
- System adapts to humans, not the reverse
- Excel is authoritative when uploaded
- Judging systems vary — Calyx adapts, no single "right way" enforced
- Calm beats clever, guidance beats power

## User Preferences
- Do NOT build UI
- Do NOT invent judging rules
- Do NOT restructure the project
- Focus on correctness, clarity, stability
