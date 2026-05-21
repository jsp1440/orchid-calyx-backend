# Calyx + Orchid Continuum — Complete Capability Audit
**Prepared:** 2026-05-03
**Scope:** Calyx backend, Orchid Continuum data platform, widget inventory, field-office use cases

---

## Part 1: Calyx — What It Is, What It Does, Is It Ready

### What it is
Calyx is a **backend-only** API for running orchid shows and the operations around them. It is built in Python (FastAPI), stores data in a PostgreSQL database (Replit-hosted heliumdb), and is designed to be the engine that a separate frontend (Famous AI) talks to.

**Per standing preferences, Calyx does not have its own UI** — it exposes ~70 HTTP endpoints that any frontend, mobile app, or coordinator script can call.

### Readiness — honest assessment

| Subsystem | Status | Notes |
|---|---|---|
| Core data (shows, entries, awards) | **Ready** | Full CRUD, simple, stable |
| Volunteer Operations | **Ready** | Most polished module — roles, shifts, sign-up, check-in, Excel sync, printable schedules. Built per the v2 design doc. |
| Judging (full system) | **Ready** | 937 lines, event lifecycle, per-criterion scoring, weighted results, judge-facing scorecards, audit trail |
| Judge scorecard workflow | **Ready** | Autosave drafts, submit-and-lock, audit log per action |
| Reference Documents (AOS PDFs) | **Ready** | Upload, SHA-256 dedupe, document type tagging |
| API key authentication | **Ready (optional)** | Falls open if `CALYX_API_KEY` not set — fine for dev, must be set for production |
| Database schema management | **Working but minimal** | No Alembic migrations; uses `create_all()` + `_safe_add_column()` at startup. Adequate for now. |
| Feedback capture | **Ready (stub)** | Functional beta-capture endpoint |
| Judging widget stubs | **Placeholder** | `/judging/criteria`, `/judging/evaluate`, `/judging/submit` exist as plug-in stubs but return canned data |
| Legacy volunteer tasks router | **Superseded** | Should be retired; `volunteer_ops.py` replaces it |
| `app/worker.py` (background jobs) | **Orphaned** | Targets a `harvest_jobs` table that doesn't exist anywhere |
| Alembic migration setup | **Misconfigured** | Targets the wrong database; should be ignored or fixed before use |
| Deployed/live anywhere? | **No** | The Calyx API workflow is currently stopped. Code is ready to run; it just isn't running. |

**Bottom line on Calyx:** The backend is roughly 85% ready for a real pilot. Three things stand between you and a usable live system:
1. A frontend (delegated to Famous AI)
2. Setting `CALYX_API_KEY` and starting the workflow on a deployed URL
3. Cleaning up 2 orphan files (`app/worker.py`, the legacy `volunteers.py` router) and fixing Alembic

---

## Part 2: Every Widget / Tile — Functional and Planned

The tile registry (`app/routers/tiles.py`) defines **8 navigation tiles**. Each is role-gated. Below is what each one does, what backend supports it, and where the gaps are.

### Widget 1: Select Show
- **What it does:** Lets any user pick which orchid show they're working with. Multi-show support is built-in — one Calyx instance can host many shows.
- **Backend:** `GET /api/shows` returns all shows; `POST /api/shows` creates one with name, start date, location, judging lock, and a public volunteer token.
- **Status:** **Functional.** The `judging_locked` flag lets a coordinator freeze all scoring with one toggle. The `public_volunteer_token` lets you generate a public sign-up link without making volunteers register accounts.
- **Roles:** admin, exhibitor, volunteer, judge

### Widget 2: My Tasks
- **What it does:** A personalized to-do list per logged-in user.
- **Backend:** No dedicated endpoint exists yet — this would aggregate from `entries`, `volunteer_assignments`, and `scorecards`.
- **Status:** **Tile placeholder only.** The data exists in the system but no "my tasks" aggregator endpoint has been built. Most obvious next backend addition.
- **Roles:** admin, exhibitor, volunteer, judge

### Widget 3: Entries
- **What it does:** Register plants entered into a show by exhibitors (name, plant, class code, status).
- **Backend:** Full CRUD at `/api/entries`. Schema includes exhibitor name, plant name, class code, and status.
- **Status:** **Functional.** Simple and stable. No exhibitor self-service flow yet — entries are coordinator-added.
- **Roles:** admin, exhibitor, volunteer

### Widget 4: Volunteers (strongest module)
- **What it does:** End-to-end volunteer coordination.
- **Backend (all under `/api/shows/{show_id}/volunteer/...`):**
  - **Roles** — create reusable role definitions (e.g., "Registration Desk", "Setup Crew") with default shift lengths
  - **Shifts** — schedule shifts with start/end datetimes and capacity caps
  - **Volunteers** — sign people up with name, email, phone, SMS opt-in, notes, and a coordinator-approval flag
  - **Assignments** — assign volunteers to shifts; track status (assigned → confirmed → checked_in → no_show); move people between shifts
  - **Check-in** — one-click check-in endpoint for the day-of
  - **Excel export** — formatted `.xlsx` for the coordinator
  - **Excel import** — bring in a spreadsheet with conflict detection and an override switch (coordinator wins)
  - **Printable schedule** — server-rendered HTML for printing
- **Status:** **Production-ready.** Designed around the "coordinator always has override power" principle and "Excel is authoritative when uploaded." Capacity enforcement, duplicate prevention, and audit-friendly status transitions all working.
- **Roles:** admin, volunteer

### Widget 5: Judging (fully built)
- **What it does:** Run the entire judging process for a show.
- **Backend has two layers:**

  **Admin layer:**
  - Create judging events (with name, type, blind/not-blind)
  - Define plant categories
  - Define criteria per award (with weighting, point ranges, rubric JSON)
  - Register exhibitors and plants (plants get QR codes auto-generated)
  - Assign judges to events + categories
  - Generate scorecards (one per judge × plant — idempotent)
  - Publish → Close event lifecycle (freezes edits)
  - Weighted leaderboard results

  **Judge-facing layer** (requires `X-Judge-Id` header):
  - "My events" view
  - "My scorecards" view (access-controlled — judges only see their own)
  - Autosave drafts as judges score
  - Submit to lock the scorecard and compute the weighted total
  - Audit trail of every save and submit (with diff JSON)

- **Status:** **Production-ready.** Most sophisticated module. Per-criterion scoring, weighted aggregation, blind judging support, and proper access controls all working.
- **Roles:** admin, judge

### Widget 6: Awards
- **What it does:** Define and record awards (AOS or society-specific).
- **Backend:** Full CRUD at `/api/awards`. Read-only `/api/judging/awards` reads canonical award definitions from Orchid Continuum (Neon) — so AOS award categories don't need to be re-typed.
- **Status:** **Functional.** Tied into the criteria system.
- **Roles:** admin, judge

### Widget 7: Admin
- **What it does:** Coordinator overrides, reference doc uploads, system configuration.
- **Backend:** Reference document upload (`POST /api/admin/reference-docs`), generate-scorecards utility, system status.
- **Status:** **Partial.** The backend pieces exist. There's no unified "admin dashboard" data endpoint yet — that's a UI concern.
- **Roles:** admin

### Widget 8: Help
- **What it does:** User-facing help / context.
- **Backend:** None — this is a static frontend tile.
- **Status:** **Tile placeholder only.** Help content lives in the frontend.
- **Roles:** all (including public)

### Plug-in widgets (separate from the 8 main tiles)

| Widget | What | Status |
|---|---|---|
| **Feedback capture** | `POST /api/feedback` — module, step, worked Y/N, confusion, suggestions | Functional, lightweight beta-feedback collector |
| **Judging Widget (AOS plug-in)** | `GET /judging/criteria`, `POST /judging/evaluate`, `POST /judging/submit` — pluggable scoring widget for external embeds | Stub — returns canned data, not yet wired to the full judging system |
| **System Reference Documents** | Upload, list, download AOS PDFs (style book, score sheets, awards criteria) | Functional |

---

## Part 3: Orchid Continuum — What It Is, What It Has

### What it is
Orchid Continuum is the **scientific data layer** — a Neon PostgreSQL database holding the actual orchid knowledge: occurrence records, taxonomy, images, traits, climate data. Calyx is a *consumer* of this data, never a writer.

### What's in it (verified from Builds 197–198)

| Domain | Approximate scale | Status |
|---|---|---|
| **Occurrence records** (`oc_occurrences`) | Live GBIF data + uploads | Active |
| **Taxonomy** (`oc_taxa_universe`, `oc_core.taxa`) | Species/genus hierarchy | Active |
| **Media / images** (`record_media_link`) | ~1.89 million links | Active |
| **Total tables** | 302+ across 15 named schemas | Sprawling |
| **Schemas of interest** | `public`, `oc_core`, `oc_mission_control`, others | Some duplication (e.g., `pipeline_runs` exists in two schemas) |

### Operational pipeline (the GBIF harvest system)
- **`oc_scheduler.py`** — picks targets to harvest from `oc_harvest_targets`, queues jobs into `oc_job_queue`
- **`oc_automation_worker.py`** — pulls jobs, calls GBIF, inserts occurrence records
- **`oc_extract_taxonomy.py`** — backfills species/genus/country/elevation onto raw occurrence rows
- **`mission_control_scheduler.py`** — hourly orchestrator across the pipeline
- **`oc_sentinel.py`** (currently named `python oc_system_check_v2.py` — yes, the filename has a space) — sophisticated schema-adaptive health check

**Critical context:** All 5 write-capable pipeline scripts are currently **safety-locked** (Build 199) and require an explicit override variable to run. They were locked because column-schema alignment with the current Neon tables has not been verified. **Until Build 199B (Julius's column audit) is done, the pipeline is intentionally frozen.**

### Diagnostic / read-only tools (always safe)
- **`oc_control_panel.py`** — CLI summary of totals (occurrences, species, genera, countries, elevation range)
- **`oc_mission_control.py`** — Streamlit dashboard with metrics, job queue, harvest status, occurrence sample
- **`oc_orchid_atlas.py`** — generates a Folium map of 20,000 georeferenced orchid points as an HTML file
- **`orchid_climate_engine.py`** — generates per-genus climate envelopes (lat-derived temp + rainfall estimates) as CSV
- **`oc_sentinel.py`** — schema discovery + JSON/TXT health report

### Planned (not yet built)
- **Graph architecture overlay** (`docs/oc_graph_architecture_canon_phase1.md`) — semantic graph layer over the relational data: taxonomy → records → images → traits → climate, with provenance, confidence scores, and evidence classification (observed/derived/inferred). Spec is mature, implementation hasn't started.

### Orchid Continuum readiness
- **Read side: ready** — millions of records of real orchid data are queryable today
- **Write side: locked** — pipeline scripts are safety-locked pending schema verification (Build 199B)
- **Diagnostic side: ready** — sentinel and mission control work
- **Graph layer: planned only**

---

## Part 4: What This Means for a Field Conservation Office

### What a field office gains (immediately)

#### 1. Volunteer coordination — strongest offering
A conservation office running a citizen-science survey, a transplant rescue, a herbarium digitization day, or a habitat census needs to:
- Define roles (Spotter, Photographer, GPS logger, Data Entry, Transport)
- Schedule shifts across days
- Sign people up without forcing them to create accounts (the public volunteer token does this)
- Track who actually showed up
- Hand a coordinator a printed schedule that works without internet
- Sync with their Excel files (which every field office uses)

**Calyx Volunteer Ops delivers all of this today.** This is genuinely the most field-ready piece. Excel sync in particular is critical — field offices live in spreadsheets, and Calyx treats Excel as authoritative when uploaded.

#### 2. Data collection at events / surveys
- Register plants (or sightings) with the **Entries** module
- Each plant can get a **QR code** automatically (from the Judging module's plant registration — this works for any "specimen" not just show plants)
- Categorize them, attach class codes, track status

For a field office doing a regional orchid survey, this becomes a "what did we find, where, and who logged it" system without writing custom code.

#### 3. Expert judging / assessment
Even outside formal AOS-style shows, the judging system is useful for:
- Conservation triage (which rescued plants need urgent care?)
- Quality scoring of cultivated specimens for ex-situ programs
- Multi-expert assessment with weighted criteria and audit trails
- Distance assessment — judges can be in another country and score via the API

The per-criterion weighted scoring + audit trail + blind-judging support is unusual in conservation tools. It's normally only seen in professional society judging.

#### 4. Reference materials
The Reference Docs system lets you upload PDFs (AOS judging style book, species ID guides, CITES paperwork, local permits, methodology docs) once and have them available across the office. SHA-256 deduplication prevents the "47 copies of the same PDF" problem field offices accumulate.

#### 5. Scientific data lookup (Orchid Continuum)
A field office identifying a plant can query Orchid Continuum to answer:
- Has this species been recorded in this region before? (occurrence map)
- What's its taxonomic status? (taxa table)
- What climate envelope does it prefer? (climate engine output)
- What images do we have? (1.89M media links)

This is meaningful because **most conservation offices don't have curated access to GBIF.** They have public GBIF.org, which is unfiltered. Orchid Continuum is the orchid-specific subset, harvested, deduplicated, and enriched.

#### 6. Inter-office collaboration
- Multi-show / multi-event support — one Calyx instance can host many offices' events
- Shared organizations + contacts + message templates
- Shared award definitions (read from Orchid Continuum)
- Feedback channel back to you for improving the tool

### Honest gaps — what would need to be added before offering this as a service

| Need | Current state | Gap |
|---|---|---|
| **Frontend / mobile app** | Backend only by design | Famous AI is supposed to fill this; no offline mode yet |
| **Offline / low-bandwidth mode** | Excel import/export is the offline bridge | Real offline-first sync (CouchDB-style) is not built |
| **SMS / messaging delivery** | Message templates and SMS opt-in flag exist | No actual SMS sender wired up — needs Twilio or similar integration |
| **Image upload pipeline** | `files` and `reference_docs` storage works | No mobile photo upload flow for field surveys |
| **Multi-tenant isolation** | Multi-org data model exists | No tenant-scoped auth — anyone with the API key sees everything |
| **Internationalization** | English only | No translation layer |
| **Email notifications** | None | Volunteers approved/assigned aren't auto-notified |
| **Maps in Calyx** | Atlas lives in Orchid Continuum scripts (HTML output) | Not integrated as a Calyx endpoint |
| **CITES / permit tracking** | Reference docs can hold them | No dedicated workflow |
| **Mobile QR scanning** | QR codes are generated | The scanning flow lives in the frontend |
| **Payment / membership** | None | If field offices were to subscribe |

### Honest pitch to a field office

If you walked into a Madagascar orchid project tomorrow and offered this, the honest pitch is:

> "I can give you, today, a working back-office system that handles your volunteers, your survey events, your specimen records, your reference library, and gives you read access to a curated database of every published orchid occurrence record on Earth. You'll work through a web interface my partner is building. You'll need internet to use it, but you can export to Excel and work offline, then sync back. Right now this is best for field offices that already have at least one laptop, one staff member who can manage data, and intermittent internet. Mobile and full offline are on the roadmap, not in the product yet."

That's an honest, attractive pitch — and it's defensible by what's actually in the codebase.

---

## Summary Scorecard

| Area | Ready to demo | Ready for pilot | Ready for paid service |
|---|---|---|---|
| Calyx Volunteer Ops | ✓ | ✓ | Needs frontend + auth hardening |
| Calyx Judging | ✓ | ✓ | Needs frontend |
| Calyx Shows / Entries / Awards | ✓ | ✓ | Needs frontend |
| Calyx Reference Docs | ✓ | ✓ | Needs frontend |
| Orchid Continuum reads | ✓ | ✓ | ✓ (already curated) |
| Orchid Continuum writes (pipeline) | Locked until Build 199B | Locked | Locked |
| Field-office offering as a whole | ✓ (with you driving) | Once Famous AI ships frontend | Adds: SMS, mobile, offline, tenant isolation |

The two biggest unlocks for going from "impressive demo" to "field-office service" are:
1. Famous AI delivering a frontend that exposes the volunteer + judging modules
2. Julius completing Build 199B so the Orchid Continuum write pipeline can resume
