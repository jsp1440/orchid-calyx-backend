from __future__ import annotations

from typing import Any, Dict, List, Set
import json

TILE_REGISTRY: Dict[str, Any] = {
  "version": "0.1",
  "tiles": [
    {
      "tile_id": "select_show",
      "label": "Select Show",
      "icon_metaphor": "calendar with location pin",
      "audiences": [
        "admin",
        "exhibitor",
        "volunteer",
        "judge"
      ],
      "scope": "global",
      "modes": [],
      "priority": "critical",
      "primary_workflow": "Choose organization and show context",
      "route_suggestion": "/shows/select",
      "offline_behavior": "read_only",
      "data_dependencies": [],
      "notes": "If offline, only previously cached shows are selectable."
    },
    {
      "tile_id": "my_tasks",
      "label": "My Tasks",
      "icon_metaphor": "checklist with clock",
      "audiences": [
        "admin",
        "exhibitor",
        "volunteer",
        "judge"
      ],
      "scope": "global",
      "modes": [
        "practice",
        "live",
        "offline",
        "degraded"
      ],
      "priority": "critical",
      "primary_workflow": "Resume role-based tasks and wizards",
      "route_suggestion": "/me/tasks",
      "offline_behavior": "read_only",
      "data_dependencies": [],
      "notes": "Offline shows only cached assignments and queued actions."
    },
    {
      "tile_id": "exhibitor_portal",
      "label": "Exhibitor",
      "icon_metaphor": "plant tag on a pot",
      "audiences": [
        "exhibitor",
        "admin"
      ],
      "scope": "global",
      "modes": [
        "practice",
        "live",
        "offline",
        "degraded"
      ],
      "priority": "secondary",
      "primary_workflow": "Manage exhibitor entries and status",
      "route_suggestion": "/me/exhibitor",
      "offline_behavior": "read_only",
      "data_dependencies": []
    },
    {
      "tile_id": "volunteer_portal",
      "label": "Volunteer",
      "icon_metaphor": "hand with badge",
      "audiences": [
        "volunteer",
        "admin"
      ],
      "scope": "global",
      "modes": [
        "practice",
        "live",
        "offline",
        "degraded"
      ],
      "priority": "critical",
      "primary_workflow": "Access volunteer shifts and show-day tools",
      "route_suggestion": "/me/volunteer",
      "offline_behavior": "read_only",
      "data_dependencies": []
    },
    {
      "tile_id": "judge_portal",
      "label": "Judge",
      "icon_metaphor": "clipboard with ribbon",
      "audiences": [
        "judge",
        "admin"
      ],
      "scope": "global",
      "modes": [
        "practice",
        "live",
        "offline",
        "degraded"
      ],
      "priority": "critical",
      "primary_workflow": "Enter judging workspace and queues",
      "route_suggestion": "/me/judging",
      "offline_behavior": "queues",
      "data_dependencies": [],
      "notes": "Offline allows drafting evaluations and queues submissions if permitted by show policy."
    },
    {
      "tile_id": "show_admin",
      "label": "Admin",
      "icon_metaphor": "gear with building",
      "audiences": [
        "admin"
      ],
      "scope": "global",
      "modes": [
        "practice",
        "live"
      ],
      "priority": "secondary",
      "primary_workflow": "Manage organizations, shows, and exports",
      "route_suggestion": "/admin",
      "offline_behavior": "requires_online",
      "data_dependencies": []
    },
    {
      "tile_id": "training_help",
      "label": "Help",
      "icon_metaphor": "lifebuoy with document",
      "audiences": [
        "admin",
        "exhibitor",
        "volunteer",
        "judge",
        "public"
      ],
      "scope": "global",
      "modes": [
        "practice",
        "live",
        "offline",
        "degraded"
      ],
      "priority": "secondary",
      "primary_workflow": "Open training assets and quick guides",
      "route_suggestion": "/help",
      "offline_behavior": "read_only",
      "data_dependencies": [],
      "notes": "Cache key docs for offline."
    },
    {
      "tile_id": "system_status",
      "label": "Status",
      "icon_metaphor": "signal bars with wrench",
      "audiences": [
        "admin",
        "volunteer",
        "judge"
      ],
      "scope": "global",
      "modes": [
        "practice",
        "live",
        "offline",
        "degraded"
      ],
      "priority": "critical",
      "primary_workflow": "View connectivity, sync queue, and device status",
      "route_suggestion": "/status",
      "offline_behavior": "works_offline",
      "data_dependencies": []
    },
    {
      "tile_id": "show_setup",
      "label": "Show Setup",
      "icon_metaphor": "clipboard with gear",
      "audiences": [
        "admin"
      ],
      "scope": "show",
      "modes": [
        "practice",
        "live"
      ],
      "priority": "critical",
      "primary_workflow": "Configure show settings and structure",
      "route_suggestion": "/shows/{show_id}/setup",
      "offline_behavior": "requires_online",
      "data_dependencies": [
        "show_id"
      ]
    },
    {
      "tile_id": "entry_registration",
      "label": "Entry & Reg",
      "icon_metaphor": "tag with plus sign",
      "audiences": [
        "admin",
        "exhibitor",
        "volunteer"
      ],
      "scope": "show",
      "modes": [
        "practice",
        "live",
        "offline",
        "degraded"
      ],
      "priority": "critical",
      "primary_workflow": "Register entries and manage check-in/out",
      "route_suggestion": "/shows/{show_id}/entries",
      "offline_behavior": "queues",
      "data_dependencies": [
        "show_id"
      ]
    },
    {
      "tile_id": "judging",
      "label": "Judging",
      "icon_metaphor": "gavel over checklist",
      "audiences": [
        "judge",
        "admin"
      ],
      "scope": "show",
      "modes": [
        "practice",
        "live",
        "offline",
        "degraded"
      ],
      "priority": "critical",
      "primary_workflow": "Open judging workspace for this show",
      "route_suggestion": "/shows/{show_id}/judging",
      "offline_behavior": "queues",
      "data_dependencies": [
        "show_id"
      ]
    },
    {
      "tile_id": "volunteers",
      "label": "Volunteers",
      "icon_metaphor": "people with badges",
      "audiences": [
        "volunteer",
        "admin"
      ],
      "scope": "show",
      "modes": [
        "practice",
        "live",
        "offline",
        "degraded"
      ],
      "priority": "critical",
      "primary_workflow": "Manage shifts, roster, and check-ins",
      "route_suggestion": "/shows/{show_id}/volunteers",
      "offline_behavior": "read_only",
      "data_dependencies": [
        "show_id"
      ]
    },
    {
      "tile_id": "vendors",
      "label": "Vendors",
      "icon_metaphor": "storefront",
      "audiences": [
        "admin",
        "volunteer",
        "public"
      ],
      "scope": "show",
      "modes": [
        "practice",
        "live",
        "offline",
        "degraded"
      ],
      "priority": "secondary",
      "primary_workflow": "View and manage vendor list",
      "route_suggestion": "/shows/{show_id}/vendors",
      "offline_behavior": "read_only",
      "data_dependencies": [
        "show_id"
      ]
    },
    {
      "tile_id": "zones_displays",
      "label": "Zones",
      "icon_metaphor": "map grid with pins",
      "audiences": [
        "admin",
        "volunteer",
        "judge",
        "public"
      ],
      "scope": "show",
      "modes": [
        "practice",
        "live",
        "offline",
        "degraded"
      ],
      "priority": "critical",
      "primary_workflow": "View zones and move items between areas",
      "route_suggestion": "/shows/{show_id}/zones",
      "offline_behavior": "read_only",
      "data_dependencies": [
        "show_id"
      ]
    },
    {
      "tile_id": "training_documents",
      "label": "Documents",
      "icon_metaphor": "stack of papers",
      "audiences": [
        "admin",
        "volunteer",
        "judge",
        "exhibitor"
      ],
      "scope": "show",
      "modes": [
        "practice",
        "live",
        "offline",
        "degraded"
      ],
      "priority": "secondary",
      "primary_workflow": "Open show-specific training assets",
      "route_suggestion": "/shows/{show_id}/training",
      "offline_behavior": "read_only",
      "data_dependencies": [
        "show_id"
      ]
    },
    {
      "tile_id": "awards_certificates",
      "label": "Awards",
      "icon_metaphor": "ribbon with document",
      "audiences": [
        "admin",
        "judge"
      ],
      "scope": "show",
      "modes": [
        "practice",
        "live"
      ],
      "priority": "critical",
      "primary_workflow": "Review and produce award outputs",
      "route_suggestion": "/shows/{show_id}/awards",
      "offline_behavior": "requires_online",
      "data_dependencies": [
        "show_id"
      ],
      "notes": "Finalization should be blocked in offline/degraded."
    },
    {
      "tile_id": "reports_exports",
      "label": "Reports",
      "icon_metaphor": "chart with download arrow",
      "audiences": [
        "admin"
      ],
      "scope": "show",
      "modes": [
        "practice",
        "live"
      ],
      "priority": "secondary",
      "primary_workflow": "Generate exports and summary reports",
      "route_suggestion": "/shows/{show_id}/reports",
      "offline_behavior": "requires_online",
      "data_dependencies": [
        "show_id"
      ]
    },
    {
      "tile_id": "review_queue",
      "label": "Review Queue",
      "icon_metaphor": "inbox tray",
      "audiences": [
        "judge",
        "admin"
      ],
      "scope": "mode",
      "modes": [
        "practice",
        "live",
        "offline",
        "degraded"
      ],
      "priority": "critical",
      "primary_workflow": "Open next items ready for review",
      "route_suggestion": "wizard:judging_review_queue",
      "offline_behavior": "read_only",
      "data_dependencies": [
        "show_id"
      ]
    },
    {
      "tile_id": "evaluate_entry",
      "label": "Evaluate",
      "icon_metaphor": "form with pencil",
      "audiences": [
        "judge",
        "admin"
      ],
      "scope": "mode",
      "modes": [
        "practice",
        "live",
        "offline",
        "degraded"
      ],
      "priority": "critical",
      "primary_workflow": "Capture evaluation using configured fields",
      "route_suggestion": "wizard:judging_evaluate_entry",
      "offline_behavior": "queues",
      "data_dependencies": [
        "show_id",
        "entry_id"
      ]
    },
    {
      "tile_id": "compare_entries",
      "label": "Compare",
      "icon_metaphor": "two cards side by side",
      "audiences": [
        "judge",
        "admin"
      ],
      "scope": "mode",
      "modes": [
        "practice",
        "live"
      ],
      "priority": "secondary",
      "primary_workflow": "Side-by-side review and notes",
      "route_suggestion": "wizard:judging_compare",
      "offline_behavior": "requires_online",
      "data_dependencies": [
        "show_id"
      ]
    },
    {
      "tile_id": "resolve_flags",
      "label": "Resolve",
      "icon_metaphor": "warning flag",
      "audiences": [
        "admin",
        "judge",
        "volunteer"
      ],
      "scope": "mode",
      "modes": [
        "practice",
        "live",
        "offline",
        "degraded"
      ],
      "priority": "critical",
      "primary_workflow": "Fix conflicts and unblock workflow states",
      "route_suggestion": "/shows/{show_id}/issues",
      "offline_behavior": "read_only",
      "data_dependencies": [
        "show_id"
      ]
    },
    {
      "tile_id": "finalize_results",
      "label": "Finalize",
      "icon_metaphor": "lock with ribbon",
      "audiences": [
        "admin",
        "judge"
      ],
      "scope": "mode",
      "modes": [
        "practice",
        "live"
      ],
      "priority": "critical",
      "primary_workflow": "Lock a stage and publish outputs",
      "route_suggestion": "wizard:judging_finalize",
      "offline_behavior": "requires_online",
      "data_dependencies": [
        "show_id"
      ]
    },
    {
      "tile_id": "judge_sync",
      "label": "Judge Sync",
      "icon_metaphor": "refresh arrows with shield",
      "audiences": [
        "judge",
        "admin"
      ],
      "scope": "mode",
      "modes": [
        "practice",
        "live",
        "offline",
        "degraded"
      ],
      "priority": "critical",
      "primary_workflow": "Manage queued actions and conflicts",
      "route_suggestion": "/sync",
      "offline_behavior": "works_offline",
      "data_dependencies": []
    },
    {
      "tile_id": "check_in",
      "label": "Check In",
      "icon_metaphor": "scan lines with tag",
      "audiences": [
        "volunteer",
        "admin"
      ],
      "scope": "mode",
      "modes": [
        "practice",
        "live",
        "offline",
        "degraded"
      ],
      "priority": "critical",
      "primary_workflow": "Scan and record entry check-in",
      "route_suggestion": "wizard:entry_checkin",
      "offline_behavior": "queues",
      "data_dependencies": [
        "show_id",
        "entry_id"
      ],
      "notes": "Stores local event receipt and queues server update."
    },
    {
      "tile_id": "check_out",
      "label": "Check Out",
      "icon_metaphor": "exit arrow with tag",
      "audiences": [
        "volunteer",
        "admin"
      ],
      "scope": "mode",
      "modes": [
        "practice",
        "live",
        "offline",
        "degraded"
      ],
      "priority": "critical",
      "primary_workflow": "Scan and record entry check-out",
      "route_suggestion": "wizard:entry_checkout",
      "offline_behavior": "queues",
      "data_dependencies": [
        "show_id",
        "entry_id"
      ]
    },
    {
      "tile_id": "runner_tasks",
      "label": "Runner Tasks",
      "icon_metaphor": "running figure with clipboard",
      "audiences": [
        "volunteer",
        "admin"
      ],
      "scope": "mode",
      "modes": [
        "practice",
        "live",
        "offline",
        "degraded"
      ],
      "priority": "secondary",
      "primary_workflow": "Simple move and assist task queue",
      "route_suggestion": "/shows/{show_id}/runner",
      "offline_behavior": "read_only",
      "data_dependencies": [
        "show_id"
      ]
    },
    {
      "tile_id": "photo_queue",
      "label": "Photo Queue",
      "icon_metaphor": "camera with queue lines",
      "audiences": [
        "volunteer",
        "admin"
      ],
      "scope": "mode",
      "modes": [
        "practice",
        "live",
        "offline",
        "degraded"
      ],
      "priority": "secondary",
      "primary_workflow": "Capture and attach photos to entries",
      "route_suggestion": "wizard:photo_capture",
      "offline_behavior": "queues",
      "data_dependencies": [
        "show_id",
        "entry_id"
      ],
      "notes": "Stores photos locally, queues upload + association."
    },
    {
      "tile_id": "volunteer_check_in",
      "label": "Volunteer In",
      "icon_metaphor": "badge with checkmark",
      "audiences": [
        "volunteer",
        "admin"
      ],
      "scope": "mode",
      "modes": [
        "practice",
        "live",
        "offline",
        "degraded"
      ],
      "priority": "critical",
      "primary_workflow": "Mark volunteer present for shift",
      "route_suggestion": "wizard:volunteer_checkin",
      "offline_behavior": "queues",
      "data_dependencies": [
        "show_id",
        "shift_id"
      ]
    },
    {
      "tile_id": "roster_now",
      "label": "Roster Now",
      "icon_metaphor": "people list",
      "audiences": [
        "volunteer",
        "admin"
      ],
      "scope": "mode",
      "modes": [
        "practice",
        "live",
        "offline",
        "degraded"
      ],
      "priority": "critical",
      "primary_workflow": "View who is on duty and where",
      "route_suggestion": "/shows/{show_id}/roster",
      "offline_behavior": "read_only",
      "data_dependencies": [
        "show_id"
      ]
    },
    {
      "tile_id": "offline_check_in",
      "label": "Offline Check-In",
      "icon_metaphor": "tag with device",
      "audiences": [
        "volunteer",
        "admin"
      ],
      "scope": "offline",
      "modes": [
        "offline",
        "degraded"
      ],
      "priority": "critical",
      "primary_workflow": "Record check-in locally for later sync",
      "route_suggestion": "wizard:offline_entry_checkin",
      "offline_behavior": "works_offline",
      "data_dependencies": [
        "show_id",
        "entry_id"
      ]
    },
    {
      "tile_id": "offline_check_out",
      "label": "Offline Check-Out",
      "icon_metaphor": "exit arrow with device",
      "audiences": [
        "volunteer",
        "admin"
      ],
      "scope": "offline",
      "modes": [
        "offline",
        "degraded"
      ],
      "priority": "critical",
      "primary_workflow": "Record check-out locally for later sync",
      "route_suggestion": "wizard:offline_entry_checkout",
      "offline_behavior": "works_offline",
      "data_dependencies": [
        "show_id",
        "entry_id"
      ]
    },
    {
      "tile_id": "queue_actions",
      "label": "Queue Actions",
      "icon_metaphor": "stacked receipts",
      "audiences": [
        "admin",
        "volunteer",
        "judge"
      ],
      "scope": "offline",
      "modes": [
        "offline",
        "degraded"
      ],
      "priority": "critical",
      "primary_workflow": "Review and retry queued actions",
      "route_suggestion": "/offline/queue",
      "offline_behavior": "works_offline",
      "data_dependencies": []
    },
    {
      "tile_id": "sync_when_online",
      "label": "Sync",
      "icon_metaphor": "cloud with refresh arrows",
      "audiences": [
        "admin",
        "volunteer",
        "judge"
      ],
      "scope": "offline",
      "modes": [
        "offline",
        "degraded"
      ],
      "priority": "critical",
      "primary_workflow": "Sync queued actions when connected",
      "route_suggestion": "/offline/sync",
      "offline_behavior": "works_offline",
      "data_dependencies": []
    },
    {
      "tile_id": "roster_snapshot",
      "label": "Roster Snap",
      "icon_metaphor": "people list with clock",
      "audiences": [
        "volunteer",
        "admin"
      ],
      "scope": "offline",
      "modes": [
        "offline",
        "degraded"
      ],
      "priority": "secondary",
      "primary_workflow": "Read-only roster from last sync",
      "route_suggestion": "/offline/roster",
      "offline_behavior": "read_only",
      "data_dependencies": [
        "show_id"
      ]
    },
    {
      "tile_id": "maps_zones_offline",
      "label": "Zones",
      "icon_metaphor": "map pin with cache",
      "audiences": [
        "volunteer",
        "admin",
        "judge",
        "public"
      ],
      "scope": "offline",
      "modes": [
        "offline",
        "degraded"
      ],
      "priority": "secondary",
      "primary_workflow": "View zones and notes offline",
      "route_suggestion": "/offline/zones",
      "offline_behavior": "read_only",
      "data_dependencies": [
        "show_id"
      ]
    },
    {
      "tile_id": "emergency_help",
      "label": "Emergency Help",
      "icon_metaphor": "lifebuoy with phone",
      "audiences": [
        "admin",
        "volunteer",
        "judge"
      ],
      "scope": "offline",
      "modes": [
        "offline",
        "degraded"
      ],
      "priority": "secondary",
      "primary_workflow": "Open emergency procedures and contacts",
      "route_suggestion": "/offline/help",
      "offline_behavior": "works_offline",
      "data_dependencies": []
    }
  ]
}

_ALLOWED_SCOPES = {"global","show","mode","offline"}
_ALLOWED_MODES = {"practice","live","offline","degraded"}
_ALLOWED_PRIORITIES = {"critical","secondary"}
_ALLOWED_OFFLINE = {"works_offline","queues","read_only","requires_online"}
_REQUIRED_KEYS = {
  "tile_id","label","icon_metaphor","audiences","scope","modes","priority",
  "primary_workflow","route_suggestion","offline_behavior","data_dependencies"
}

def _validate_registry(reg: Dict[str, Any]) -> None:
    if not isinstance(reg, dict):
        raise ValueError("TILE_REGISTRY must be a dict")
    if "version" not in reg or not isinstance(reg["version"], str) or not reg["version"].strip():
        raise ValueError("TILE_REGISTRY.version must be a non-empty string")
    tiles = reg.get("tiles")
    if not isinstance(tiles, list) or not tiles:
        raise ValueError("TILE_REGISTRY.tiles must be a non-empty list")

    seen: Set[str] = set()
    for i, t in enumerate(tiles):
        if not isinstance(t, dict):
            raise ValueError(f"Tile at index {i} must be a dict")
        missing = _REQUIRED_KEYS - set(t.keys())
        if missing:
            raise ValueError(f"Tile {t.get('tile_id','<missing tile_id>')} missing keys: {sorted(missing)}")

        tile_id = t["tile_id"]
        if tile_id in seen:
            raise ValueError(f"Duplicate tile_id: {tile_id}")
        seen.add(tile_id)

        scope = t["scope"]
        if scope not in _ALLOWED_SCOPES:
            raise ValueError(f"Tile {tile_id} has invalid scope: {scope}")

        modes = t["modes"]
        if not isinstance(modes, list):
            raise ValueError(f"Tile {tile_id} modes must be a list")
        bad_modes = [m for m in modes if m not in _ALLOWED_MODES]
        if bad_modes:
            raise ValueError(f"Tile {tile_id} has invalid modes: {bad_modes}")

        pr = t["priority"]
        if pr not in _ALLOWED_PRIORITIES:
            raise ValueError(f"Tile {tile_id} has invalid priority: {pr}")

        ob = t["offline_behavior"]
        if ob not in _ALLOWED_OFFLINE:
            raise ValueError(f"Tile {tile_id} has invalid offline_behavior: {ob}")

        aud = t["audiences"]
        if not isinstance(aud, list) or not aud:
            raise ValueError(f"Tile {tile_id} audiences must be a non-empty list")

        # Must be JSON-serializable (avoid sneaky set/bytes)
        try:
            json.dumps(t)
        except TypeError as e:
            raise ValueError(f"Tile {tile_id} is not JSON-serializable: {e}") from e

_validate_registry(TILE_REGISTRY)
