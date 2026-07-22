from __future__ import annotations

import re

from .models import (
    ApiContractSpecification,
    ComponentSpecification,
    ConflictImpact,
    CrossCuttingContract,
    DataContractSpecification,
    ImplementationPhase,
    NavigationSpecification,
    PageSpecification,
    ReadinessRecord,
    ReadinessStatus,
    StateSpecification,
)


PAGES = (
    ("Dashboard", "/conservatory", ()),
    ("My Plants", "/conservatory/plants", ()),
    ("Plant Detail", "/conservatory/plants/{plant_id}", ("plant_id",)),
    ("QR Scanner", "/conservatory/scan", ()),
    ("Add Plant", "/conservatory/plants/new", ()),
    ("Repot Plant", "/conservatory/plants/{plant_id}/repot", ("plant_id",)),
    ("Bloom History", "/conservatory/plants/{plant_id}/blooms", ("plant_id",)),
    (
        "Environmental History",
        "/conservatory/plants/{plant_id}/environment",
        ("plant_id",),
    ),
    ("Media Gallery", "/conservatory/plants/{plant_id}/media", ("plant_id",)),
    ("Search", "/conservatory/search", ()),
    ("Reports", "/conservatory/reports", ()),
    ("Settings", "/conservatory/settings", ()),
)

COMPONENT_NAMES = (
    "Application Shell",
    "Primary Navigation",
    "Mobile Navigation",
    "Breadcrumbs",
    "Orchid Card",
    "Plant Header",
    "Scientific Name Display",
    "Taxonomy Status Badge",
    "QR Badge",
    "QR Scan Result",
    "Photo Gallery",
    "Media Viewer",
    "Trait Table",
    "Parentage Tree",
    "History Timeline",
    "Bloom Event Card",
    "Repotting Event Card",
    "Culture Event Card",
    "Environmental Graph",
    "Accessible Chart Alternative",
    "Location Badge",
    "Reminder Panel",
    "Tag History",
    "Citation Panel",
    "Provenance Viewer",
    "Collection Table",
    "Search Field",
    "Search Result Card",
    "Filter Panel",
    "Sort Control",
    "Pagination Control",
    "Empty State",
    "Loading State",
    "Error State",
    "Confirmation Dialog",
    "Form Field",
    "Validation Summary",
    "Privacy Control",
    "Export Panel",
)

STATE_DOMAINS = (
    "authenticated user",
    "active collection",
    "collection filters",
    "search state",
    "plant detail state",
    "QR scan state",
    "form state",
    "validation state",
    "media state",
    "timeline state",
    "environmental history state",
    "reminder state",
    "permissions",
    "privacy settings",
    "synchronization",
    "offline cache",
    "audit context",
)

DATA_NAMES = (
    "Collection",
    "Plant Passport",
    "Plant Identity",
    "Scientific Name",
    "Taxonomic Status",
    "Parentage",
    "Plant Location",
    "QR Identifier",
    "Plant Media",
    "Tag Record",
    "Bloom Event",
    "Repotting Event",
    "Culture Event",
    "Environmental Reading",
    "Environmental Summary",
    "Reminder",
    "Award",
    "Provenance Record",
    "Citation",
    "Export Request",
    "Search Query",
    "Search Result",
    "User Permission",
    "Sharing Policy",
)


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def api_contracts(source_plan_id: str) -> tuple[ApiContractSpecification, ...]:
    existing = (
        ApiContractSpecification(
            "api-auth-verify",
            "verify authenticated session",
            "EXISTING",
            "/verify",
            "app.security",
            None,
            source_plan_id,
            None,
            "authenticated session",
            ReadinessStatus.READY,
            None,
        ),
        ApiContractSpecification(
            "api-awards-existing",
            "generic awards records",
            "EXISTING_PARTIAL",
            "/awards",
            "app.routers.awards",
            "AwardOut",
            source_plan_id,
            None,
            "authenticated authorized user",
            ReadinessStatus.PARTIAL,
            "Existing awards API is not collection/plant-scoped.",
        ),
    )
    proposed = (
        (
            "collections",
            "GET/POST",
            "/api/conservatory/collections",
            "collection inventory root",
        ),
        (
            "plants",
            "GET/POST",
            "/api/conservatory/collections/{collection_id}/plants",
            "paginated plant collection",
        ),
        (
            "plant-passport",
            "GET/PATCH",
            "/api/conservatory/plants/{plant_id}",
            "plant passport and controlled correction",
        ),
        (
            "qr",
            "POST",
            "/api/conservatory/qr/resolve",
            "resolve QR without embedding mutable data",
        ),
        (
            "repotting",
            "GET/POST",
            "/api/conservatory/plants/{plant_id}/repotting-events",
            "append repotting history",
        ),
        (
            "blooms",
            "GET/POST",
            "/api/conservatory/plants/{plant_id}/bloom-events",
            "append bloom history",
        ),
        (
            "culture",
            "GET/POST",
            "/api/conservatory/plants/{plant_id}/culture-events",
            "append culture history",
        ),
        (
            "environment",
            "GET",
            "/api/conservatory/plants/{plant_id}/environment",
            "paginated readings and summaries",
        ),
        (
            "media",
            "GET/POST",
            "/api/conservatory/plants/{plant_id}/media",
            "licensed media metadata and upload intent",
        ),
        (
            "tags",
            "GET/POST",
            "/api/conservatory/plants/{plant_id}/tag-events",
            "append tag history",
        ),
        ("search", "GET", "/api/conservatory/search", "authorized collection search"),
        (
            "reminders",
            "GET/POST/PATCH",
            "/api/conservatory/reminders",
            "plant-linked reminders",
        ),
        (
            "reports",
            "POST",
            "/api/conservatory/reports",
            "privacy-scoped report request",
        ),
        (
            "exports",
            "POST/GET",
            "/api/conservatory/exports",
            "audited asynchronous export",
        ),
        (
            "settings",
            "GET/PATCH",
            "/api/conservatory/settings",
            "owner privacy and sharing policy",
        ),
    )
    values = []
    for name, method, route, purpose in proposed:
        values.append(
            ApiContractSpecification(
                f"api-{name}",
                purpose,
                "PROPOSED",
                None,
                None,
                None,
                source_plan_id,
                {
                    "method": method,
                    "route": route,
                    "purpose": purpose,
                    "authentication": "required",
                    "authorization": "collection role and field policy",
                    "path_parameters": [
                        part[1:-1] for part in route.split("/") if part.startswith("{")
                    ],
                    "query_parameters": ["cursor", "limit", "sort"]
                    if "GET" in method
                    else [],
                    "request_body": f"{name.replace('-', ' ').title()}Request when method accepts a body",
                    "response_body": f"Versioned {name.replace('-', ' ').title()}Response with provenance",
                    "validation": "reject unknown fields, invalid identifiers, units, rights, and unauthorized scope",
                    "errors": [
                        "400 validation",
                        "401 unauthenticated",
                        "403 unauthorized",
                        "404 not found",
                        "409 version conflict",
                        "503 unavailable",
                    ],
                    "idempotency": "required for writes via idempotency key and immutable operation fingerprint",
                    "pagination": "cursor-based for collections and histories",
                    "provenance": "return source IDs, versions, timestamps, actors, and confidence where applicable",
                    "audit": "append authenticated action without private payload leakage",
                    "privacy": "redact protected locality, ownership, media, and sharing fields by policy",
                },
                "authenticated collection role",
                ReadinessStatus.BLOCKED,
                f"Backend capability '{purpose}' does not exist on remote main; BUILD-092 must not call it until a separately authorized backend build implements it.",
            )
        )
    return existing + tuple(values)


def page_specs(source_plan_id: str) -> tuple[PageSpecification, ...]:
    mapping = {
        "Dashboard": ("api-collections", "api-reminders"),
        "My Plants": ("api-plants",),
        "Plant Detail": ("api-plant-passport", "api-tags"),
        "QR Scanner": ("api-qr",),
        "Add Plant": ("api-plants",),
        "Repot Plant": ("api-repotting",),
        "Bloom History": ("api-blooms",),
        "Environmental History": ("api-environment",),
        "Media Gallery": ("api-media",),
        "Search": ("api-search",),
        "Reports": ("api-reports", "api-exports"),
        "Settings": ("api-settings",),
    }
    values = []
    for index, (name, route, params) in enumerate(PAGES, 1):
        contracts = mapping[name]
        dependency = "Required My Conservatory backend contracts are proposed but not implemented."
        if name in {"Plant Detail", "QR Scanner", "Add Plant", "Reports", "Settings"}:
            dependency += " A carried BUILD-090C material conflict also requires an authorized decision."
        components = (
            "Application Shell",
            "Breadcrumbs",
            "Loading State",
            "Empty State",
            "Error State",
        )
        values.append(
            PageSpecification(
                f"page-{slug(name)}",
                name,
                route,
                params,
                f"Implement the approved BUILD-090C {name} planning contract without changing its decisions.",
                ("collection owner", "authorized collaborator"),
                tuple(f"mc-req-{n:02d}" for n in range(1, 19)),
                (source_plan_id,),
                (
                    "application header",
                    "primary content",
                    "status region",
                    "supporting details",
                ),
                (name, "primary task"),
                ("provenance", "help", "related history"),
                components,
                (
                    "authenticated user",
                    "active collection",
                    "versioned product data",
                    "provenance",
                ),
                tuple(f"capability:{item}" for item in contracts),
                contracts,
                tuple(f"{slug(item)}Request" for item in contracts),
                tuple(f"{slug(item)}Response" for item in contracts),
                {
                    "authorization": "deny before data fetch; distinguish 401 and 403 without leaking existence",
                    "validation": "field, identifier, unit, rights, version, and permission validation",
                    "loading": "named status with retained navigation and no layout-dependent meaning",
                    "empty": "explain legitimate absence and offer only authorized next actions",
                    "error": "recoverable specific error; preserve safe input; never silently overwrite",
                    "retry": "idempotent retry with bounded backoff for unavailable reads",
                    "offline": "private read-only cache only where policy permits; queue no sensitive write by default",
                    "responsive": "single task mobile, adaptive tablet, multi-region desktop",
                    "keyboard": "logical order, skip link, all actions operable, no keyboard trap",
                    "screen_reader": "landmarks, headings, names, descriptions, status and validation announcements",
                    "focus": "move to page heading on navigation; restore trigger after dialogs/errors",
                    "reduced_motion": "no essential motion; honor preference",
                    "scientific": "retain names, uncertainty, scope, units, observation/interpretation and conflicts",
                    "provenance": "show source, version, actor/time and citations near derived content",
                    "privacy": "private by default; redact locality, ownership and media by authorization",
                    "state_transitions": (
                        "idle",
                        "loading",
                        "ready",
                        "empty",
                        "error",
                        "stale",
                    ),
                },
                (f"mc.page.{slug(name)}.viewed", f"mc.page.{slug(name)}.failed"),
                (
                    f"{name} follows the approved route and task hierarchy.",
                    "Keyboard and screen-reader acceptance passes.",
                    "Scientific and provenance context is not simplified.",
                    "No private values enter telemetry.",
                ),
                (dependency,),
                ReadinessStatus.BLOCKED,
            )
        )
    return tuple(values)


def component_specs() -> tuple[ComponentSpecification, ...]:
    pages = tuple(name for name, _, _ in PAGES)
    values = []
    for name in COMPONENT_NAMES:
        science = name in {
            "Plant Header",
            "Scientific Name Display",
            "Taxonomy Status Badge",
            "Trait Table",
            "Parentage Tree",
            "Environmental Graph",
            "Citation Panel",
            "Provenance Viewer",
        }
        privacy = name in {
            "Photo Gallery",
            "Media Viewer",
            "Location Badge",
            "Privacy Control",
            "Export Panel",
            "Provenance Viewer",
        }
        values.append(
            ComponentSpecification(
                f"component-{slug(name)}",
                name,
                f"Reusable specification for {name}.",
                pages,
                {
                    "data": "versioned typed contract",
                    "permissions": "UserPermission",
                    "provenance": "ProvenanceRecord[]",
                },
                {
                    "render_state": "semantic state description",
                    "selected_id": "string|null",
                },
                {
                    "id": "stable string",
                    "label": "localized string",
                    "disabled": "boolean",
                },
                (f"mc.component.{slug(name)}.action",),
                ("idle", "loading", "ready", "empty", "error"),
                {
                    "loading": "use shared named loading state",
                    "error": "use shared recoverable error state",
                    "accessibility": "native semantics first; named controls, descriptions and non-color meaning",
                    "keyboard": "documented logical tab and activation behavior; no custom shortcut conflict",
                    "focus": "visible focus and deterministic restoration",
                    "responsive": "content reflows without information loss",
                    "scientific": "preserve uncertainty and qualifiers"
                    if science
                    else "do not transform scientific content",
                    "provenance": "retain and expose source references where applicable",
                    "privacy": "field-level redaction before presentation"
                    if privacy
                    else "consume only authorized projection",
                },
                (
                    "typed data contract",
                    "authorization projection",
                    "shared accessibility contract",
                ),
                (
                    f"{name} passes keyboard and screen-reader tests.",
                    "All states are specified.",
                    "No private data enters telemetry.",
                ),
                ReadinessStatus.PARTIAL,
            )
        )
    return tuple(values)


def navigation_spec() -> NavigationSpecification:
    registry = tuple(
        {
            "page_id": f"page-{slug(name)}",
            "route": route,
            "parameters": params,
            "authenticated": True,
        }
        for name, route, params in PAGES
    )
    graph = {
        "page-dashboard": (
            "page-my-plants",
            "page-search",
            "page-reports",
            "page-settings",
            "page-qr-scanner",
        ),
        "page-my-plants": ("page-plant-detail", "page-add-plant"),
        "page-plant-detail": (
            "page-repot-plant",
            "page-bloom-history",
            "page-environmental-history",
            "page-media-gallery",
        ),
    }
    rules = {
        "deep_links": "authenticate, authorize collection and plant, then resolve or return non-leaking 404/403",
        "qr": "scan token routes through proposed resolver then to plant passport; unknown and duplicate states remain explicit",
        "search": "result activates plant passport route while preserving return query and focus",
        "breadcrumbs": "derive from route registry; Dashboard > My Plants > Plant > Subview",
        "back": "return to prior authorized collection state; never rely solely on browser history after QR",
        "mobile": ("Dashboard", "My Plants", "Scan", "Search", "More"),
        "tablet": "adaptive primary rail and contextual secondary navigation",
        "desktop": "persistent primary navigation with breadcrumbs",
        "invalid": "404 with safe navigation",
        "unauthorized": "403 without existence disclosure",
        "missing_plant": "not-found state with collection return and no leaked metadata",
    }
    return NavigationSpecification(
        "navigation-my-conservatory-v1", registry, graph, rules
    )


def state_specs() -> tuple[StateSpecification, ...]:
    return tuple(
        StateSpecification(
            f"state-{slug(name)}",
            name,
            "smallest owning feature boundary",
            "authenticated collection session",
            "authoritative backend response; URL for shareable navigation state",
            "validate identity, permissions, route parameters and cached version before use",
            (
                "uninitialized->loading",
                "loading->ready|empty|error",
                "ready->stale->loading",
            ),
            "memory by default; encrypted bounded cache only where privacy policy permits",
            "invalidate on user/collection/version/permission/privacy change",
            "conditional request with version/etag and explicit stale state",
            "only reversible low-risk changes with idempotency key; never optimistic privacy or scientific identity",
            "restore prior immutable snapshot and announce failure",
            "surface 409 and require explicit refresh/merge; no last-write-wins",
            "read-only authorized projection; no sensitive queued writes by default",
            (
                "no secret or protected locality",
                "clear on logout or permission loss",
                "exclude values from telemetry",
            ),
        )
        for name in STATE_DOMAINS
    )


def data_specs() -> tuple[DataContractSpecification, ...]:
    common = {
        "id": "UUID/string",
        "version": "positive integer",
        "created_at": "RFC3339 timestamp",
    }
    return tuple(
        DataContractSpecification(
            f"data-{slug(name)}",
            name,
            {
                **common,
                "data": f"typed {name} fields",
                "provenance": "ProvenanceRecord[]",
                "uncertainty": "Uncertainty|null",
            },
            ("id", "version", "provenance"),
            ("uncertainty", "data"),
            (
                "reject unknown fields",
                "validate identifiers and versions",
                "preserve qualifiers, negation and source scope",
            ),
            {"measurements": "UCUM-compatible explicit unit and method context"},
            "structured status, confidence decomposition, qualifier, alternatives, and rationale reference",
            (
                "source identity",
                "source version",
                "actor/component",
                "timestamp",
                "integrity hash",
            ),
            "RESTRICTED_COLLECTION_DATA",
            "JSON object; RFC3339 times; explicit null versus absent; deterministic key semantics",
            "immutable version with supersession; history remains recoverable",
            ReadinessStatus.PARTIAL,
        )
        for name in DATA_NAMES
    )


def cross_cutting(pages, components) -> tuple[CrossCuttingContract, ...]:
    page_ids = tuple(item.page_id for item in pages)
    component_ids = tuple(item.component_id for item in components)
    accessibility = (
        "semantic landmarks and one logical heading hierarchy",
        "accessible names, descriptions, labels and validation summaries",
        "status announcements without focus theft",
        "complete keyboard access, logical order, skip navigation and focus restoration",
        "modal focus containment and trigger restoration",
        "reduced motion, 200% zoom/text scaling and color-independent meaning",
        "chart/time-series table alternatives",
        "meaningful image alternatives and non-camera QR alternative",
        "recoverable mobile errors",
    )
    scientific = (
        "display accepted names separately from synonyms and authorship",
        "preserve hybrid and cultivar notation",
        "show parentage direction and uncertainty",
        "label uncertain identification and unresolved taxonomy",
        "separate observation from interpretation",
        "retain measurement value, unit, method, date and location context",
        "show source attribution and provenance",
        "redact conservation-sensitive locality",
        "represent missing and conflicting data explicitly",
    )
    privacy = (
        "private by default and owner-controlled sharing",
        "role-aware field-level authorization",
        "protect locality, ownership, collection and media visibility",
        "require export permission and audited authenticated writes",
        "return non-leaking unauthorized states",
        "redact restricted fields before serialization and caching",
        "telemetry records identifiers/categories only, never location, ownership, collection content, media or free text",
    )
    return tuple(
        CrossCuttingContract(
            f"contract-{kind}",
            kind.upper(),
            rules,
            {pid: rules for pid in page_ids},
            {cid: rules for cid in component_ids},
        )
        for kind, rules in (
            ("accessibility", accessibility),
            ("scientific-presentation", scientific),
            ("privacy-security", privacy),
        )
    )


def conflict_impacts(conflicts) -> tuple[ConflictImpact, ...]:
    definitions = (
        (
            "simplicity versus scientific completeness",
            ("page-plant-detail", "page-my-plants"),
            ("component-scientific-name-display", "component-provenance-viewer"),
            "SCIENTIFIC",
        ),
        (
            "mobile versus desktop workflows",
            tuple(f"page-{slug(x[0])}" for x in PAGES),
            ("component-application-shell", "component-mobile-navigation"),
            "UX",
        ),
        (
            "rapid entry versus validation",
            ("page-add-plant", "page-repot-plant"),
            ("component-form-field", "component-validation-summary"),
            "PRODUCT_OWNER",
        ),
        (
            "privacy versus sharing",
            ("page-settings", "page-reports", "page-media-gallery"),
            ("component-privacy-control", "component-export-panel"),
            "PRIVACY_SECURITY",
        ),
        (
            "novice versus expert users",
            ("page-dashboard", "page-plant-detail", "page-search"),
            ("component-orchid-card", "component-trait-table"),
            "UX",
        ),
    )
    values = []
    for index, (title, pages, components, owner) in enumerate(definitions):
        source = conflicts[index] if index < len(conflicts) else None
        conflict_id = source.conflict_id if source else f"missing-conflict-{index + 1}"
        values.append(
            ConflictImpact(
                conflict_id,
                title,
                "DECISION_REQUIRED",
                pages,
                components,
                ("api-plant-passport", "api-settings", "api-plants"),
                ("identical approved decision must be reflected in affected criteria",),
                owner,
                (
                    "final component behavior",
                    "implementation acceptance sign-off",
                    "production release",
                ),
            )
        )
    return tuple(values)


def phases() -> tuple[ImplementationPhase, ...]:
    definitions = (
        (
            "Frontend Foundation",
            (
                "application shell",
                "routing",
                "authentication boundary",
                "design tokens",
                "accessibility foundation",
                "API client",
                "error handling",
            ),
        ),
        (
            "Navigation and Collection Shell",
            ("navigation", "dashboard shell", "My Plants shell", "search foundation"),
        ),
        (
            "Collection Management",
            ("collection table", "filters", "Add Plant", "identity", "locations", "QR"),
        ),
        (
            "Plant Passport",
            (
                "Plant Detail",
                "taxonomy",
                "parentage",
                "provenance",
                "media",
                "tag history",
            ),
        ),
        (
            "Event Histories",
            ("bloom", "repotting", "culture", "reminders", "timelines"),
        ),
        (
            "Environmental Integration",
            (
                "environment history",
                "graphs",
                "accessible alternatives",
                "sensor provenance",
                "missing data",
            ),
        ),
        (
            "Reports and Exports",
            ("reports", "exports", "permissions", "privacy review"),
        ),
        (
            "Accessibility and Scientific Review",
            (
                "keyboard",
                "screen reader",
                "scientific formatting",
                "uncertainty",
                "provenance",
            ),
        ),
        (
            "Integration and Acceptance Testing",
            (
                "API integration",
                "end-to-end",
                "responsive",
                "privacy",
                "accessibility",
                "regression",
            ),
        ),
    )
    return tuple(
        ImplementationPhase(
            f"phase-{index}",
            name,
            ("prior phase accepted",) if index > 1 else ("BUILD-091 merged",),
            deliverables,
            (f"phase-{index - 1}",) if index > 1 else (),
            (
                "required product APIs are not implemented",
                "five material conflicts remain DECISION_REQUIRED",
            )
            if index >= 3
            else (),
            (
                "deliverables have typed contracts",
                "accessibility and privacy criteria pass",
                "no planning decision is silently changed",
            ),
            f"BUILD-{91 + index}",
            ReadinessStatus.PARTIAL if index < 3 else ReadinessStatus.BLOCKED,
        )
        for index, (name, deliverables) in enumerate(definitions, 1)
    )


def readiness_records(pages, components, apis, data, sequence, source_plan_id):
    records = []
    for kind, values in (
        ("PAGE", pages),
        ("COMPONENT", components),
        ("API", apis),
        ("DATA", data),
        ("PHASE", sequence),
    ):
        for item in values:
            identity = getattr(
                item,
                "page_id",
                getattr(
                    item,
                    "component_id",
                    getattr(item, "contract_id", getattr(item, "phase_id", "unknown")),
                ),
            )
            status = item.readiness_status
            dependency = (
                None
                if status is ReadinessStatus.READY
                else (
                    getattr(item, "exact_dependency", None)
                    or "Requires unresolved API, data, review, or conflict dependency documented in this specification."
                )
            )
            role = "TECHNICAL_FEASIBILITY" if kind in {"API", "DATA", "PHASE"} else "UX"
            records.append(
                ReadinessRecord(
                    f"readiness-{kind.casefold()}-{slug(identity)}",
                    kind,
                    identity,
                    status,
                    dependency,
                    source_plan_id,
                    role,
                    "BUILD-092",
                )
            )
    return tuple(records)
