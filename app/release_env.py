"""Release 1 environment checklist: which variables exist, never their values.

One catalogue feeds three consumers so they cannot drift apart:

* ``scripts/preflight_release1_env.py`` (operator preflight, env-only);
* ``GET /api/system/config-readiness`` (owner-session-only);
* the README environment table (a test asserts every name is documented).

Presence means "set to a non-blank value". Nothing here returns, logs, hashes
or measures a value: the report carries names, the required/optional flag and
presence booleans only.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class EnvVariable:
    name: str
    required: bool
    default: str
    purpose: str
    when_missing: str
    # Other names that satisfy a required variable (read in this order after it).
    fallbacks: tuple[str, ...] = ()


REQUIRED = True
OPTIONAL = False

RELEASE1_ENV: tuple[EnvVariable, ...] = (
    # --- storage -----------------------------------------------------------
    EnvVariable(
        "DATABASE_URL",
        REQUIRED,
        "unset (SQLite `sqlite:///./calyx.db`)",
        "Production PostgreSQL connection string (app/database.py, evidence feedback, runtime, literature).",
        "Show data falls back to a local SQLite file (not durable on Render); evidence feedback falls back to the file store and reports itself non-durable; PostgreSQL-backed routes are unavailable.",
    ),
    EnvVariable(
        "PGHOST",
        OPTIONAL,
        "unset",
        "Legacy Replit PostgreSQL host. When set it takes precedence over DATABASE_URL for show data (app/database.py), together with PGUSER/PGPASSWORD/PGDATABASE/PGPORT.",
        "Nothing; DATABASE_URL is used. Leave unset on Render unless show data deliberately lives elsewhere.",
    ),
    EnvVariable(
        "CALYX_EVIDENCE_FEEDBACK_ROOT",
        OPTIONAL,
        "`data/evidence_feedback`",
        "File-store directory for evidence feedback, used only when DATABASE_URL is unset (app/evidence_feedback/routes.py).",
        "With no DATABASE_URL either, feedback is written to the default local directory and every response carries the NON-DURABLE warning.",
    ),
    # --- backend and owner authentication -----------------------------------
    EnvVariable(
        "CALYX_API_KEY",
        REQUIRED,
        "unset",
        "Service credential expected in the `X-API-Key` header (app/security.py).",
        "Every X-API-Key-protected route returns 401 `API key authentication is not configured`.",
    ),
    EnvVariable(
        "CALYX_OWNER_ACCESS_CODE",
        REQUIRED,
        "unset",
        "Owner sign-in access code (app/security.py).",
        "Owner sign-in returns 503 `Owner access is not configured`; no owner session can be issued.",
    ),
    EnvVariable(
        "CALYX_OWNER_SESSION_SECRET",
        REQUIRED,
        "unset",
        "HMAC key that signs and verifies owner session tokens (app/security.py).",
        "Owner session issuance returns 503 `Owner session signing is not configured`; owner-only routes stay 401/503.",
    ),
    EnvVariable(
        "CALYX_OWNER_SESSION_TTL_SECONDS",
        OPTIONAL,
        "`3600` (clamped to 300..86400)",
        "Owner session lifetime.",
        "Default lifetime is used.",
    ),
    EnvVariable(
        "CALYX_OWNER_COOKIE_SECURE",
        OPTIONAL,
        "true when `RENDER` is set, else false",
        "Marks the owner session cookie Secure.",
        "Derived from `RENDER`.",
    ),
    EnvVariable(
        "CALYX_OWNER_COOKIE_SAMESITE",
        OPTIONAL,
        "`none` when the cookie is Secure, else `lax`",
        "SameSite attribute of the owner session cookie; invalid values become `lax`.",
        "Derived default is used.",
    ),
    EnvVariable(
        "ORCHID_JUDGE_ADMIN_KEY",
        OPTIONAL,
        "unset",
        "Legacy `X-Orchid-Admin-Key` for judging admin routes (app/security.py `require_admin`).",
        "Routes guarded by `require_admin` return 503 `Admin authentication is not configured`.",
    ),
    # --- member (Supabase) authentication ------------------------------------
    EnvVariable(
        "OC_SUPABASE_URL",
        REQUIRED,
        "unset",
        "Supabase project URL used to verify member bearer tokens (app/member_auth.py).",
        "Member tokens cannot be verified, so member reads and member feedback are refused; owner and API-key access are unaffected.",
        fallbacks=("OCU_SUPABASE_URL",),
    ),
    EnvVariable(
        "OCU_SUPABASE_URL",
        OPTIONAL,
        "unset",
        "Fallback for OC_SUPABASE_URL (read only when OC_SUPABASE_URL is blank).",
        "Nothing when OC_SUPABASE_URL is set.",
    ),
    EnvVariable(
        "OC_SUPABASE_ANON_KEY",
        REQUIRED,
        "unset",
        "Supabase anonymous (publishable) key sent when verifying member tokens (app/member_auth.py).",
        "Member tokens cannot be verified, so member reads and member feedback are refused.",
        fallbacks=("OCU_SUPABASE_ANON_KEY",),
    ),
    EnvVariable(
        "OCU_SUPABASE_ANON_KEY",
        OPTIONAL,
        "unset",
        "Fallback for OC_SUPABASE_ANON_KEY (read only when OC_SUPABASE_ANON_KEY is blank).",
        "Nothing when OC_SUPABASE_ANON_KEY is set.",
    ),
    EnvVariable(
        "OC_MEMBER_READS_ENABLED",
        OPTIONAL,
        "unset = enabled",
        "Kill switch for member read access; only `1/true/yes/on` enable it once set (app/member_auth.py).",
        "Unset keeps member reads on; any other set value turns them off and members fall back to owner-path 401s.",
    ),
    # --- evidence feedback -----------------------------------------------------
    EnvVariable(
        "CALYX_EVIDENCE_FEEDBACK_ACTOR_REF_SECRET",
        OPTIONAL,
        "unset (falls back to CALYX_OWNER_SESSION_SECRET, domain-separated)",
        "HMAC key for opaque submitter/reviewer references in the review queue (app/evidence_feedback/review.py).",
        "Falls back to the owner session secret; with neither set, references read `actor-unavailable` instead of any identity.",
    ),
    # --- browser origins -------------------------------------------------------
    EnvVariable(
        "CORS_ALLOW_ORIGIN",
        OPTIONAL,
        "unset (built-in Mission Control origins only)",
        "Comma-separated extra browser origins allowed on credentialed routes (app/routers/health.py); `*` is ignored.",
        "Only the built-in origins are allowed; other frontends' browser calls fail CORS.",
    ),
    EnvVariable(
        "CORS_ALLOW_ORIGINS",
        OPTIONAL,
        "`*`",
        "Allowed origins for the Show Day profile only (app/show_app.py).",
        "All origins are allowed on the Show Day profile.",
    ),
    EnvVariable(
        "RENDER",
        OPTIONAL,
        "set by Render",
        "Platform marker; defaults the owner cookie to Secure.",
        "Owner cookie is not Secure unless CALYX_OWNER_COOKIE_SECURE says so.",
    ),
    # --- show day -------------------------------------------------------------
    EnvVariable(
        "CALYX_TAG_BASE_URL",
        OPTIONAL,
        "unset",
        "Frontend scan-page URL encoded into entry-tag QR codes (app/routers/show_day.py).",
        "QR codes encode the bare tag token instead of a scan link.",
    ),
    # --- provider safety (NO-API) ------------------------------------------------
    EnvVariable(
        "NO_API_MODE",
        OPTIONAL,
        "`true`",
        "Global paid-provider brake; anything other than `false` blocks live provider calls (Firecrawl provider and runtime).",
        "Treated as `true`: paid provider calls are blocked.",
    ),
    EnvVariable(
        "PROVIDER_AUTHORIZED",
        OPTIONAL,
        "`false`",
        "Second explicit authorization required, with NO_API_MODE=false, before any live Firecrawl call.",
        "Treated as `false`: live Firecrawl calls are blocked (`PROVIDER_NOT_AUTHORIZED`).",
    ),
    # --- Firecrawl literature pilot (disabled by default) -------------------------
    EnvVariable(
        "FIRECRAWL_ENABLED",
        OPTIONAL,
        "`false`",
        "Enables the Firecrawl literature pilot.",
        "Pilot is disabled (`FIRECRAWL_DISABLED`).",
    ),
    EnvVariable(
        "FIRECRAWL_KILL_SWITCH",
        OPTIONAL,
        "`false`",
        "Any value other than `false` stops the pilot.",
        "Pilot is not killed by this switch.",
    ),
    EnvVariable(
        "FIRECRAWL_DRY_RUN",
        OPTIONAL,
        "`true`",
        "Fixture-only execution; no network.",
        "Dry run: live calls are refused.",
    ),
    EnvVariable(
        "FIRECRAWL_PILOT_MODE",
        OPTIONAL,
        "`true`",
        "Restricts live execution to the pilot issue and genus.",
        "Pilot restrictions stay on.",
    ),
    EnvVariable(
        "FIRECRAWL_API_KEY",
        OPTIONAL,
        "unset",
        "Firecrawl credential for live acquisition.",
        "Live acquisition is blocked (`FIRECRAWL_KEY_UNAVAILABLE`).",
    ),
    EnvVariable(
        "FIRECRAWL_APPROVED_DOMAINS",
        OPTIONAL,
        "empty",
        "Comma-separated allowlist of acquisition domains.",
        "No domain is approved, so nothing is fetched.",
    ),
    EnvVariable(
        "FIRECRAWL_MAX_SEARCHES_PER_TASK",
        OPTIONAL,
        "`1`",
        "Per-task search cap.",
        "Default cap.",
    ),
    EnvVariable(
        "FIRECRAWL_MAX_DOCUMENTS",
        OPTIONAL,
        "`2`",
        "Per-task document cap.",
        "Default cap.",
    ),
    EnvVariable(
        "FIRECRAWL_RETRY_CAP",
        OPTIONAL,
        "`2`",
        "Retry ceiling per call.",
        "Default cap.",
    ),
    EnvVariable(
        "FIRECRAWL_BACKOFF_SECONDS",
        OPTIONAL,
        "`1`",
        "Retry backoff.",
        "Default backoff.",
    ),
    EnvVariable(
        "FIRECRAWL_MAX_CALL_COST_USD",
        OPTIONAL,
        "`0`",
        "Worst-case reserved cost per call; must be > 0 for live runs.",
        "Zero: live execution is blocked.",
    ),
    EnvVariable(
        "FIRECRAWL_DAILY_BUDGET_USD",
        OPTIONAL,
        "`0`",
        "Daily spend ceiling; must be > 0 for live runs.",
        "Zero: live execution is blocked.",
    ),
    EnvVariable(
        "FIRECRAWL_DAILY_CREDIT_CAP",
        OPTIONAL,
        "`25`",
        "Daily provider-credit ceiling.",
        "Default cap.",
    ),
    EnvVariable(
        "FIRECRAWL_PILOT_GENUS",
        OPTIONAL,
        "`Paphiopedilum`",
        "Genus the pilot is scoped to.",
        "Default genus.",
    ),
    EnvVariable(
        "FIRECRAWL_PILOT_ISSUE_NUMBER",
        OPTIONAL,
        "empty",
        "GitHub issue a live pilot run must reference.",
        "Live pilot runs are refused (`LIVE_PILOT_ISSUE_SCOPE_REQUIRED`); dry runs are unaffected.",
    ),
    EnvVariable(
        "FIRECRAWL_REQUIRED_PREDICATES",
        OPTIONAL,
        "empty",
        "Comma-separated predicate scope for the acquisition-coverage audit (app/literature_extraction/routes.py).",
        "The coverage audit runs without a predicate filter.",
    ),
)

RELEASE1_ENV_NAMES: tuple[str, ...] = tuple(v.name for v in RELEASE1_ENV)


def _present(env: Mapping[str, str], name: str) -> bool:
    value = env.get(name)
    return bool(value and value.strip())


def config_readiness(env: Mapping[str, str] | None = None) -> dict[str, object]:
    """Presence report for every Release 1 variable. Contains no values."""

    source = os.environ if env is None else env
    variables: list[dict[str, object]] = []
    missing_required: list[str] = []
    for item in RELEASE1_ENV:
        present = _present(source, item.name)
        entry: dict[str, object] = {
            "name": item.name,
            "required": item.required,
            "present": present,
        }
        if item.required:
            satisfied = present or any(_present(source, fb) for fb in item.fallbacks)
            entry["satisfied"] = satisfied
            if not satisfied:
                missing_required.append(item.name)
        variables.append(entry)
    return {
        "ready": not missing_required,
        "missing_required": missing_required,
        "variables": variables,
    }
