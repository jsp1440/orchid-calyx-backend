"""OC-COMPLETE-008 — Calyx show-management current-main audit.

Machine-readable capability inventory for every show-management area in the
current orchid-calyx-backend codebase, classified as KEEP / CONVERGE /
SUPERSEDE / GAP / RETIRED.

Includes accessibility status, security notes, and bounded child task specs.
No production migration, deployment, or data mutation.
"""

from __future__ import annotations

import json

SCHEMA_VERSION = "oc-show-management-audit/v1"
AUDIT_DATE = "2026-09-04"

# ---------------------------------------------------------------------------
# Capability inventory
# ---------------------------------------------------------------------------

CAPABILITY_INVENTORY: list[dict] = [
    # -------------------------------------------------------------------------
    # Shows / Events
    # -------------------------------------------------------------------------
    {
        "capability_id": "show_crud_flat",
        "capability": "Flat show CRUD (POST/GET/PATCH/DELETE /api/shows)",
        "area": "shows",
        "module": "app/routers/shows.py",
        "status": "CONVERGE",
        "accessible": False,
        "reason_inaccessible": "Router not registered in app/main.py",
        "child_task": "Register shows.py router in main.py and add route-registration test coverage",
        "notes": "All 5 endpoints fully implemented; registration is the only missing step",
    },
    {
        "capability_id": "show_crud_org_scoped",
        "capability": "Org-scoped show CRUD (GET/POST /api/organizations/{org_id}/shows)",
        "area": "shows",
        "module": "app/routers/calyx_core.py",
        "status": "KEEP",
        "accessible": True,
        "notes": "Implemented and registered; primary show creation path",
    },
    {
        "capability_id": "show_sub_resources",
        "capability": "Show sub-resources: contacts, message templates, events, files, integrations",
        "area": "shows",
        "module": "app/routers/calyx_core.py",
        "status": "KEEP",
        "accessible": True,
        "notes": "Implemented and registered; iCalendar export (RFC 5545) included",
    },
    {
        "capability_id": "show_judging_lock_enforcement",
        "capability": "Show judging lock — judging_locked field enforced in judging endpoints",
        "area": "shows",
        "module": "app/models.py + app/routers/judging.py",
        "status": "GAP",
        "accessible": False,
        "gap_description": (
            "judging_locked Boolean exists on Show model but is never read in any judging "
            "endpoint; lock has no effect on score writes or scorecard submission"
        ),
        "child_task": (
            "Enforce Show.judging_locked in judging endpoints — block Score/Scorecard "
            "writes when the parent show is locked"
        ),
        "notes": "Field can be set via shows.py PATCH (itself unregistered); end-to-end lock is absent",
    },
    # -------------------------------------------------------------------------
    # Entries / Exhibitors / Registration
    # -------------------------------------------------------------------------
    {
        "capability_id": "entry_crud",
        "capability": "Entry CRUD (/api/entries) — show-level plant entries",
        "area": "entries",
        "module": "app/routers/entries.py",
        "status": "KEEP",
        "accessible": True,
        "notes": "Full CRUD implemented and registered; optional show_id filter on list",
    },
    {
        "capability_id": "exhibitor_crud",
        "capability": "Exhibitor CRUD (/api/exhibitors) — judging-event-level exhibitors",
        "area": "entries",
        "module": "app/routers/judging.py",
        "status": "CONVERGE",
        "accessible": True,
        "gap_description": (
            "No PATCH or DELETE endpoints for Exhibitor; "
            "Entry (show-level) and Exhibitor (judging-event-level) have no FK link"
        ),
        "child_task": (
            "Add PATCH/DELETE for Exhibitor; document or implement Entry↔Exhibitor reconciliation"
        ),
        "notes": "POST and two GET endpoints present; PATCH/DELETE absent",
    },
    # -------------------------------------------------------------------------
    # Plant / QR Identity
    # -------------------------------------------------------------------------
    {
        "capability_id": "plant_qr_token",
        "capability": "Plant QR token (SHA-256 prefix, string only, in judging flow)",
        "area": "plant_qr",
        "module": "app/routers/judging.py",
        "status": "KEEP",
        "accessible": True,
        "notes": (
            "Auto-generated on plant creation (SHA-256 of UUID, first 12 hex, prefixed QR-); "
            "retrievable via GET /api/judging/plants/{id}"
        ),
    },
    {
        "capability_id": "plant_qr_image_conservatory",
        "capability": "QR image generation — SVG via qrcode library in conservatory flow",
        "area": "plant_qr",
        "module": "app/routers/conservatory.py",
        "status": "KEEP",
        "accessible": True,
        "notes": "Separate conservatory system; scan resolution endpoint present; CONSERVATORY_SCAN_BASE_URL required",
    },
    {
        "capability_id": "judging_qr_scan_resolution",
        "capability": "QR scan resolution in judging flow",
        "area": "plant_qr",
        "module": "app/routers/judging.py",
        "status": "GAP",
        "accessible": False,
        "gap_description": (
            "No endpoint to resolve a scanned judging QR token back to a plant record; "
            "conservatory has scan resolution, judging flow does not"
        ),
        "child_task": (
            "Add GET /api/judging/scan/{qr_token} to resolve token to plant + scorecard state"
        ),
    },
    {
        "capability_id": "judging_qr_image_render",
        "capability": "QR image rendering in judging flow",
        "area": "plant_qr",
        "module": "app/routers/judging.py",
        "status": "GAP",
        "accessible": False,
        "gap_description": (
            "Judging QR is a text token only; no endpoint renders it as an image or SVG "
            "suitable for printing or display on registration labels"
        ),
        "child_task": (
            "Add GET /api/judging/plants/{plant_id}/qr.svg to render QR as printable SVG image"
        ),
    },
    # -------------------------------------------------------------------------
    # Judging / Scorecards / Awards / Criteria
    # -------------------------------------------------------------------------
    {
        "capability_id": "judging_event_lifecycle",
        "capability": "Judging event lifecycle — create, publish, close",
        "area": "judging",
        "module": "app/routers/judging.py",
        "status": "KEEP",
        "accessible": True,
        "notes": "Status transitions draft→published→closed with published_at/closed_at timestamps",
    },
    {
        "capability_id": "judging_plant_categories",
        "capability": "Plant categories per judging event",
        "area": "judging",
        "module": "app/routers/judging.py",
        "status": "KEEP",
        "accessible": True,
        "notes": "POST/GET /api/judging/events/{event_id}/categories implemented and registered",
    },
    {
        "capability_id": "judging_awards_criteria",
        "capability": "Judging awards (read-only) and configurable criteria per award",
        "area": "judging",
        "module": "app/routers/judging.py",
        "status": "KEEP",
        "accessible": True,
        "notes": "Criterion weight, input_type, min/max/choices stored in DB; awards assumed pre-seeded",
    },
    {
        "capability_id": "judging_criteria_hardcoded_legacy",
        "capability": "Legacy hardcoded judging criteria endpoint (GET /api/judging/criteria)",
        "area": "judging",
        "module": "app/routers/judging.py",
        "status": "SUPERSEDE",
        "accessible": True,
        "child_task": (
            "Replace GET /api/judging/criteria hardcoded AOS-style list with dynamic "
            "per-event criteria from JudgingCriterion table"
        ),
        "notes": "Inline code comment acknowledges placeholder; configurable criteria exist in DB but not wired to this endpoint",
    },
    {
        "capability_id": "scorecard_autosave_submit_audit",
        "capability": "Judge-facing scorecard — autosave, submit, audit log",
        "area": "judging",
        "module": "app/routers/judging.py",
        "status": "KEEP",
        "accessible": True,
        "notes": "PUT autosave + POST submit + GET audit; weighted total computed on submit; ScorecardAuditLog written on each change",
    },
    {
        "capability_id": "scorecard_admin_generate",
        "capability": "Admin scorecard batch generation",
        "area": "judging",
        "module": "app/routers/judging.py",
        "status": "KEEP",
        "accessible": True,
        "notes": "POST /admin/judging_events/{event_id}/generate_scorecards; gated by require_admin (X-Orchid-Admin-Key)",
    },
    {
        "capability_id": "judging_results_weighted",
        "capability": "Weighted judging results and leaderboard",
        "area": "judging",
        "module": "app/routers/judging.py",
        "status": "KEEP",
        "accessible": True,
        "notes": "GET .../results returns weighted avg per judge sorted desc; legacy leaderboard via ScoreSubmission also present",
    },
    {
        "capability_id": "judge_assignments",
        "capability": "Judge assignments to judging events",
        "area": "judging",
        "module": "app/routers/judging.py",
        "status": "KEEP",
        "accessible": True,
        "notes": "POST/GET /api/judging/events/{event_id}/assignments implemented and registered",
    },
    {
        "capability_id": "judge_auth_cryptographic",
        "capability": "Cryptographic judge identity verification",
        "area": "judging",
        "module": "app/security.py",
        "status": "GAP",
        "accessible": False,
        "gap_description": (
            "require_judge extracts judge UUID from X-Judge-Id header but performs no "
            "HMAC or signed-token verification; any caller who knows a judge UUID can "
            "read and write scorecards as that judge"
        ),
        "child_task": (
            "Add HMAC or signed-token verification to require_judge; "
            "align with the existing verify_api_key constant-time HMAC pattern in security.py"
        ),
        "security_risk": "HIGH",
    },
    {
        "capability_id": "legacy_score_submissions",
        "capability": "Legacy score submissions (ScoreSubmission model, flat /api/score-submissions)",
        "area": "judging",
        "module": "app/routers/judging.py",
        "status": "SUPERSEDE",
        "accessible": True,
        "child_task": (
            "Migrate legacy ScoreSubmission consumers to per-criterion Score + Scorecard flow; "
            "deprecate POST /api/score-submissions"
        ),
        "notes": "Kept for backward compatibility; per-criterion scorecard system supersedes this",
    },
    {
        "capability_id": "show_awards",
        "capability": "Show-level award CRUD (/api/awards) — society award records",
        "area": "judging",
        "module": "app/routers/awards.py",
        "status": "KEEP",
        "accessible": True,
        "notes": "Full CRUD; linked to Entry, not to JudgingAward/Scorecard; records society awards separately from scoring",
    },
    # -------------------------------------------------------------------------
    # Volunteer Management
    # -------------------------------------------------------------------------
    {
        "capability_id": "volunteer_ops_full",
        "capability": (
            "Full volunteer schedule management — roles, shifts, assignments, "
            "check-in, xlsx export, xlsx/csv import, printable HTML schedule"
        ),
        "area": "volunteers",
        "module": "app/routers/volunteer_ops.py",
        "status": "CONVERGE",
        "accessible": False,
        "reason_inaccessible": "Router not registered in app/main.py",
        "child_task": (
            "Register volunteer_ops.py router in main.py (~600 lines, fully implemented); "
            "add router-registration and integration tests"
        ),
        "notes": (
            "Implements: role/shift/volunteer/assignment CRUD, check-in lifecycle, "
            "capacity/conflict detection, openpyxl styled export, xlsx/csv import with "
            "override_conflicts, HTML printable schedule"
        ),
    },
    {
        "capability_id": "volunteer_tasks_legacy",
        "capability": "Legacy volunteer tasks (flat /api/volunteer-tasks CRUD)",
        "area": "volunteers",
        "module": "app/routers/volunteers.py",
        "status": "SUPERSEDE",
        "accessible": False,
        "reason_inaccessible": "Router not registered in app/main.py",
        "child_task": (
            "Once volunteer_ops.py is registered, assess whether VolunteerTask model "
            "should be deprecated or kept as a lightweight task-tracker separate from scheduling"
        ),
        "notes": "59-line flat CRUD; superseded by full volunteer_ops.py schedule management",
    },
    {
        "capability_id": "volunteer_sms_dispatch",
        "capability": "SMS dispatch to opted-in volunteers",
        "area": "volunteers",
        "module": "none",
        "status": "GAP",
        "accessible": False,
        "gap_description": (
            "Volunteer.opt_in_sms Boolean field exists on model but no code ever reads it "
            "or dispatches SMS; no third-party SMS provider integration exists"
        ),
        "child_task": (
            "Implement outbound SMS dispatch for opted-in volunteers on check-in or "
            "shift-reminder trigger — gate behind explicit no-spend authorization"
        ),
        "notes": "No paid messaging integration without required authorization gate",
    },
    {
        "capability_id": "volunteer_public_token_signup",
        "capability": "Public volunteer self-signup via show token",
        "area": "volunteers",
        "module": "app/models.py",
        "status": "GAP",
        "accessible": False,
        "gap_description": (
            "Show.public_volunteer_token field exists on model but is never read or "
            "enforced in any endpoint; no public-facing volunteer signup flow exists"
        ),
        "child_task": (
            "Implement public volunteer signup endpoint gated by show.public_volunteer_token; "
            "ensure no auth bypass for coordinators"
        ),
    },
    # -------------------------------------------------------------------------
    # Reference Documents
    # -------------------------------------------------------------------------
    {
        "capability_id": "reference_docs_crud",
        "capability": "AOS reference document upload, retrieval, and download",
        "area": "reference_docs",
        "module": "app/routers/reference_docs.py",
        "status": "KEEP",
        "accessible": True,
        "notes": (
            "Upload/list/download implemented and registered; "
            "seeded AOS PDFs present in data/reference_docs/; SHA-256 hash stored on upload"
        ),
    },
    {
        "capability_id": "reference_docs_path_traversal_guard",
        "capability": "Path traversal guard on reference doc download",
        "area": "reference_docs",
        "module": "app/routers/reference_docs.py",
        "status": "GAP",
        "accessible": True,
        "gap_description": (
            "Download endpoint streams file_path directly from DB without verifying it "
            "stays within the data/reference_docs/ base directory; a poisoned DB record "
            "could read arbitrary server files"
        ),
        "child_task": (
            "Add path traversal guard: resolve file_path against REFERENCE_DOCS_BASE_DIR "
            "and assert the resolved path remains under that directory before opening"
        ),
        "security_risk": "MEDIUM",
    },
    {
        "capability_id": "reference_docs_admin_auth_alignment",
        "capability": "Reference docs admin auth pattern alignment (form field vs header)",
        "area": "reference_docs",
        "module": "app/routers/reference_docs.py",
        "status": "CONVERGE",
        "accessible": True,
        "gap_description": (
            "Admin upload uses form field api_key checked against ADMIN_API_KEY; "
            "inconsistent with standardized X-Orchid-Admin-Key header pattern in security.py"
        ),
        "child_task": (
            "Align reference_docs admin endpoints to use require_admin "
            "(X-Orchid-Admin-Key header) instead of form field api_key"
        ),
    },
    # -------------------------------------------------------------------------
    # Auth / Tenant Isolation
    # -------------------------------------------------------------------------
    {
        "capability_id": "auth_api_key_hmac",
        "capability": "API key authentication — X-API-Key HMAC constant-time compare",
        "area": "auth",
        "module": "app/security.py",
        "status": "KEEP",
        "accessible": True,
        "notes": "HMAC-SHA256 via hmac.compare_digest; used by most show/entry/judging endpoints",
    },
    {
        "capability_id": "auth_org_key_isolation",
        "capability": "Per-organization API key isolation",
        "area": "auth",
        "module": "app/security.py",
        "status": "GAP",
        "accessible": False,
        "gap_description": (
            "Single CALYX_API_KEY serves all organizations; any valid key can "
            "create/list shows for any org ID; org-scoped routes perform no per-org authorization"
        ),
        "child_task": (
            "Design per-org key scoping or caller-claims validation so org-scoped "
            "operations are restricted to the caller's organization"
        ),
    },
    {
        "capability_id": "auth_nonce_persistence",
        "capability": "Revoked owner session nonce persistence across process restarts",
        "area": "auth",
        "module": "app/security.py",
        "status": "GAP",
        "accessible": False,
        "gap_description": (
            "REVOKED_OWNER_NONCES is an in-memory set; cleared on restart, "
            "so revoked sessions could be replayed until token TTL expiry after a restart"
        ),
        "child_task": "Persist revoked nonces to DB (or Redis) so revocation survives process restart",
    },
    # -------------------------------------------------------------------------
    # Notifications / Email / SMS
    # -------------------------------------------------------------------------
    {
        "capability_id": "message_template_store_render",
        "capability": "Show message template storage and rendering",
        "area": "notifications",
        "module": "app/routers/calyx_core.py",
        "status": "KEEP",
        "accessible": True,
        "notes": (
            "POST/GET .../templates and POST .../templates/{id}/render (str.format) "
            "implemented; renders to text but does not dispatch"
        ),
    },
    {
        "capability_id": "outbound_email_dispatch",
        "capability": "Outbound email dispatch for show notifications",
        "area": "notifications",
        "module": "none",
        "status": "GAP",
        "accessible": False,
        "gap_description": (
            "No outbound email dispatch from any show endpoint; MessageLog model exists "
            "but status field is never written; template render returns text only"
        ),
        "child_task": (
            "Implement outbound email dispatch for show endpoints; "
            "write MessageLog.status on send/fail; gate any paid-provider integration "
            "behind explicit authorization"
        ),
        "notes": "No paid-provider integration without required authorization gate",
    },
    {
        "capability_id": "constituent_communications_python",
        "capability": "Constituent communications schema Python integration",
        "area": "notifications",
        "module": "migrations/20260823_oc_constituent_communications_foundation.sql",
        "status": "GAP",
        "accessible": False,
        "gap_description": (
            "oc_constituent and oc_communications DB schemas exist in a migration "
            "with consent ledger, suppression list, audience snapshots, and approval events — "
            "but have zero Python integration; schema is DB-only scaffolding"
        ),
        "child_task": (
            "Implement Python models and API for oc_communications schema; "
            "wire consent and suppression checks before any outbound send"
        ),
    },
]


# ---------------------------------------------------------------------------
# Accessors
# ---------------------------------------------------------------------------


def get_capabilities_by_status(status: str) -> list[dict]:
    return [c for c in CAPABILITY_INVENTORY if c["status"] == status]


def get_capabilities_by_area(area: str) -> list[dict]:
    return [c for c in CAPABILITY_INVENTORY if c["area"] == area]


def get_inaccessible_capabilities() -> list[dict]:
    return [c for c in CAPABILITY_INVENTORY if not c.get("accessible", True)]


def get_security_risks() -> list[dict]:
    return [c for c in CAPABILITY_INVENTORY if c.get("security_risk")]


def get_child_tasks() -> list[dict]:
    tasks = []
    for cap in CAPABILITY_INVENTORY:
        if cap.get("child_task"):
            tasks.append(
                {
                    "capability_id": cap["capability_id"],
                    "area": cap["area"],
                    "status": cap["status"],
                    "title": cap["child_task"],
                    "security_risk": cap.get("security_risk"),
                }
            )
    return tasks


def get_unregistered_routers() -> list[dict]:
    seen: set[str] = set()
    result = []
    for cap in CAPABILITY_INVENTORY:
        if cap.get("reason_inaccessible", "").startswith("Router not registered"):
            module = cap["module"]
            if module not in seen:
                seen.add(module)
                result.append(
                    {
                        "module": module,
                        "capability_id": cap["capability_id"],
                        "child_task": cap.get("child_task"),
                    }
                )
    return result


def get_audit() -> dict:
    status_counts: dict[str, int] = {}
    for cap in CAPABILITY_INVENTORY:
        status_counts[cap["status"]] = status_counts.get(cap["status"], 0) + 1

    return {
        "schema_version": SCHEMA_VERSION,
        "audit_date": AUDIT_DATE,
        "capability_count": len(CAPABILITY_INVENTORY),
        "status_counts": status_counts,
        "accessible_count": sum(1 for c in CAPABILITY_INVENTORY if c.get("accessible", True)),
        "inaccessible_count": sum(
            1 for c in CAPABILITY_INVENTORY if not c.get("accessible", True)
        ),
        "security_risk_count": len(get_security_risks()),
        "child_task_count": len(get_child_tasks()),
        "unregistered_router_count": len(get_unregistered_routers()),
        "automatic_publication": False,
        "knowledge_graph_mutation": False,
        "graph_mutation": False,
        "capabilities": CAPABILITY_INVENTORY,
        "child_tasks": get_child_tasks(),
        "unregistered_routers": get_unregistered_routers(),
        "security_risks": get_security_risks(),
    }


def serialize_audit_as_json() -> str:
    return json.dumps(get_audit(), indent=2)
