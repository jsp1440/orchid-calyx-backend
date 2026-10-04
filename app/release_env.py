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
        "Show data falls back to a local SQLite file (not durable on Render); evidence feedback falls back to the local file store; routes that need PostgreSQL, such as the Mission Control review APIs, return 503.",
    ),
    EnvVariable(
        "PGHOST",
        OPTIONAL,
        "unset",
        "Legacy Replit PostgreSQL host. When set it takes precedence over DATABASE_URL for show data (app/database.py), together with PGUSER/PGPASSWORD/PGDATABASE/PGPORT.",
        "Nothing; DATABASE_URL is used. Leave unset on Render unless show data deliberately lives elsewhere.",
    ),
    EnvVariable(
        "PGUSER",
        OPTIONAL,
        "`postgres`",
        "Read only together with PGHOST (app/database.py).",
        "Default used when PGHOST is set; ignored otherwise.",
    ),
    EnvVariable(
        "PGPASSWORD",
        OPTIONAL,
        "empty",
        "Read only together with PGHOST (app/database.py).",
        "Default used when PGHOST is set; ignored otherwise.",
    ),
    EnvVariable(
        "PGDATABASE",
        OPTIONAL,
        "`postgres`",
        "Read only together with PGHOST (app/database.py).",
        "Default used when PGHOST is set; ignored otherwise.",
    ),
    EnvVariable(
        "PGPORT",
        OPTIONAL,
        "`5432`",
        "Read only together with PGHOST (app/database.py).",
        "Default used when PGHOST is set; ignored otherwise.",
    ),
    EnvVariable(
        "CALYX_EVIDENCE_FEEDBACK_ROOT",
        OPTIONAL,
        "`data/evidence_feedback`",
        "File-store directory for evidence feedback, used only when DATABASE_URL is unset (app/evidence_feedback/routes.py).",
        "With no DATABASE_URL either, feedback is written to the default local directory, which is lost on restart or redeploy. No response says so: the backend only logs a NON-DURABLE warning once at startup, and only when APP_ENV/ENVIRONMENT is `prod`/`production` or RENDER is truthy.",
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
    EnvVariable(
        "OC_MEMBER_FEEDBACK_ENABLED",
        OPTIONAL,
        "unset = disabled",
        "Kill switch for member evidence-feedback submission; only `1/true/yes/on` enable it, and member reads must also be on (app/member_auth.py).",
        "Members get 403 `MEMBER_FEEDBACK_DISABLED` on the three member feedback routes, before any Supabase call; owner and API-key feedback are unaffected.",
    ),
    EnvVariable(
        "OC_MEMBER_FEEDBACK_RATE_LIMIT",
        OPTIONAL,
        "`20`",
        "Member feedback writes allowed per member per window per route (app/rate_limit.py; keyed on the member subject, not the IP); `0` disables the brake, a non-integer uses the default.",
        "Default limit.",
    ),
    EnvVariable(
        "OC_MEMBER_FEEDBACK_RATE_WINDOW_SECONDS",
        OPTIONAL,
        "`600`",
        "Window for OC_MEMBER_FEEDBACK_RATE_LIMIT (minimum 1); a non-integer uses the default.",
        "Default window.",
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
    # --- production markers, test fallbacks ----------------------------------
    EnvVariable(
        "APP_ENV",
        OPTIONAL,
        "unset",
        "`prod`/`production` marks a production-like host (read by evidence feedback and vision-lexicon activation, before ENVIRONMENT).",
        "Production-likeness falls back to ENVIRONMENT, then to RENDER.",
    ),
    EnvVariable(
        "ENVIRONMENT",
        OPTIONAL,
        "unset",
        "Same as APP_ENV, read only when APP_ENV is blank.",
        "Production-likeness falls back to RENDER.",
    ),
    EnvVariable(
        "TEST_DATABASE_URL",
        OPTIONAL,
        "unset",
        "Test/CI database. Several stores (for example app/persistence/state_repository.py, app/brain_mission, app/semantic) use it when DATABASE_URL is blank.",
        "Nothing. Keep it unset in production so no store falls back to a test database.",
    ),
    # --- other secrets and admin keys -----------------------------------------
    EnvVariable(
        "ADMIN_API_KEY",
        OPTIONAL,
        "unset (falls back to CALYX_API_KEY)",
        "`X-Orchid-Admin-Key` for reference-document management (app/routers/reference_docs.py).",
        "CALYX_API_KEY is used; with neither set, reference-doc admin routes refuse every request (503).",
    ),
    EnvVariable(
        "CONSTITUENT_MANAGE_SECRET",
        OPTIONAL,
        "unset (falls back to CALYX_OWNER_SESSION_SECRET)",
        "HMAC key for constituent preference-centre manage tokens (app/constituent_platform/service.py).",
        "The owner session secret is used; with neither set, no manage token is issued and every token fails verification.",
    ),
    EnvVariable(
        "MISSION_CONTROL_REVIEW_ALLOW_MEMORY",
        OPTIONAL,
        "`false`",
        "Allows an in-memory, non-durable review queue when DATABASE_URL is blank (development only; app/review_api/dependencies.py).",
        "Without DATABASE_URL the review APIs return 503 `REVIEW_DATABASE_NOT_CONFIGURED`.",
    ),
    # --- public writes and links ------------------------------------------------
    EnvVariable(
        "PUBLIC_WRITE_RATE_LIMIT",
        OPTIONAL,
        "`20`",
        "Public write requests allowed per client per window (app/rate_limit.py); a non-integer uses the default.",
        "Default limit.",
    ),
    EnvVariable(
        "PUBLIC_WRITE_RATE_WINDOW_SECONDS",
        OPTIONAL,
        "`600`",
        "Window for PUBLIC_WRITE_RATE_LIMIT (minimum 1); a non-integer uses the default.",
        "Default window.",
    ),
    EnvVariable(
        "PUBLIC_SITE_BASE_URL",
        OPTIONAL,
        "`https://orchidcontinuum.org`",
        "Base URL of public species-dossier links (app/species_dossier/routes.py).",
        "Default base URL.",
    ),
    # --- member Matrix identification and generative turns ---------------------
    EnvVariable(
        "OC_MEMBER_MATRIX_IDENTIFICATION_ENABLED",
        OPTIONAL,
        "unset = enabled",
        "Kill switch for member Matrix identification; once set only `1/true/yes/on` enable it (app/matrix_member_access.py).",
        "Unset keeps it on; any other set value turns it off for members.",
    ),
    EnvVariable(
        "OC_MEMBER_MATRIX_SESSIONS_PER_HOUR",
        OPTIONAL,
        "`30`",
        "Per-member Matrix session creations per hour; non-positive or non-integer values use the default.",
        "Default limit.",
    ),
    EnvVariable(
        "OC_MEMBER_MATRIX_WRITES_PER_MINUTE",
        OPTIONAL,
        "`120`",
        "Per-member Matrix session writes per minute; non-positive or non-integer values use the default.",
        "Default limit.",
    ),
    EnvVariable(
        "CALYX_GENERATIVE_ENTITLEMENT_MODE",
        OPTIONAL,
        "`owner_only`",
        "Who may use generative Calyx turns (app/calyx_conversation/access_economics.py).",
        "`owner_only`; an unrecognised value fails closed to `disabled`.",
    ),
    EnvVariable(
        "CALYX_GENERATIVE_MEMBER_DAILY_TURNS",
        OPTIONAL,
        "`0`",
        "Generative turns per member per day.",
        "Zero turns per member.",
    ),
    EnvVariable(
        "CALYX_GENERATIVE_DAILY_CEILING_TURNS",
        OPTIONAL,
        "unset",
        "Daily ceiling on generative turns across members.",
        "No ceiling value is configured.",
    ),
    # --- release identity -------------------------------------------------------
    EnvVariable(
        "OCU_RELEASE_SHA",
        OPTIONAL,
        "unset",
        "First choice for the deployed commit reported by the release-identity route (app/routers/release_identity.py).",
        "The next name is tried; with none set, release identity reports `commit_sha: null`, `attested: false`.",
    ),
    EnvVariable(
        "CALYX_DEPLOYED_COMMIT",
        OPTIONAL,
        "unset",
        "Second choice for the deployed commit.",
        "The next name is tried; with none set, release identity reports `commit_sha: null`, `attested: false`.",
    ),
    EnvVariable(
        "RENDER_GIT_COMMIT",
        OPTIONAL,
        "unset",
        "Third choice for the deployed commit (set by Render); also stamped on mission worker records.",
        "The next name is tried; with none set, release identity reports `commit_sha: null`, `attested: false`.",
    ),
    EnvVariable(
        "GIT_COMMIT",
        OPTIONAL,
        "unset",
        "Fourth choice for the deployed commit.",
        "The next name is tried; with none set, release identity reports `commit_sha: null`, `attested: false`.",
    ),
    EnvVariable(
        "COMMIT_SHA",
        OPTIONAL,
        "unset",
        "Fifth choice for the deployed commit.",
        "The next name is tried; with none set, release identity reports `commit_sha: null`, `attested: false`.",
    ),
    EnvVariable(
        "GIT_COMMIT_SHA",
        OPTIONAL,
        "unset",
        "Fallback for RENDER_GIT_COMMIT on mission worker records (app/missions/repositories.py).",
        "Worker records carry no commit.",
    ),
    # --- autonomous runtime loop (off unless enabled) ------------------------------
    EnvVariable(
        "CALYX_AUTOLOOP_ENABLED",
        OPTIONAL,
        "unset",
        "Any of the six runtime enable flags set true starts the autonomous runtime loop at startup (app/main.py); a flag set false blocks it.",
        "The loop stays off unless another enable flag is true.",
    ),
    EnvVariable(
        "OC_RUNNER_AUTOLOOP",
        OPTIONAL,
        "unset",
        "Any of the six runtime enable flags set true starts the autonomous runtime loop at startup (app/main.py); a flag set false blocks it.",
        "The loop stays off unless another enable flag is true.",
    ),
    EnvVariable(
        "CALYX_RUNTIME_ENABLED",
        OPTIONAL,
        "unset",
        "Any of the six runtime enable flags set true starts the autonomous runtime loop at startup (app/main.py); a flag set false blocks it.",
        "The loop stays off unless another enable flag is true.",
    ),
    EnvVariable(
        "AUTONOMOUS_RUNTIME_ENABLED",
        OPTIONAL,
        "unset",
        "Any of the six runtime enable flags set true starts the autonomous runtime loop at startup (app/main.py); a flag set false blocks it.",
        "The loop stays off unless another enable flag is true.",
    ),
    EnvVariable(
        "RUNNER_ENABLED",
        OPTIONAL,
        "unset",
        "Any of the six runtime enable flags set true starts the autonomous runtime loop at startup (app/main.py); a flag set false blocks it.",
        "The loop stays off unless another enable flag is true.",
    ),
    EnvVariable(
        "CALYX_AUTONOMOUS_ENABLED",
        OPTIONAL,
        "unset",
        "Any of the six runtime enable flags set true starts the autonomous runtime loop at startup (app/main.py); a flag set false blocks it.",
        "The loop stays off unless another enable flag is true.",
    ),
    EnvVariable(
        "CALYX_AUTONOMOUS_DISABLED",
        OPTIONAL,
        "unset",
        "Set true, keeps the autonomous runtime loop off whatever the enable flags say.",
        "The enable flags decide.",
    ),
    EnvVariable(
        "OC_RUNNER_DISABLED",
        OPTIONAL,
        "unset",
        "Set true, keeps the autonomous runtime loop off whatever the enable flags say.",
        "The enable flags decide.",
    ),
    EnvVariable(
        "CALYX_RUNTIME_DISABLED",
        OPTIONAL,
        "unset",
        "Set true, keeps the autonomous runtime loop off whatever the enable flags say.",
        "The enable flags decide.",
    ),
    EnvVariable(
        "CALYX_RUNTIME_INTERVAL_SECONDS",
        OPTIONAL,
        "`30` (minimum 5)",
        "Autonomous runtime loop interval; read before OC_RUNNER_INTERVAL_SECONDS. A non-integer uses 30.",
        "OC_RUNNER_INTERVAL_SECONDS, then 30.",
    ),
    EnvVariable(
        "OC_RUNNER_INTERVAL_SECONDS",
        OPTIONAL,
        "`30` (minimum 5)",
        "Fallback for CALYX_RUNTIME_INTERVAL_SECONDS.",
        "30 seconds.",
    ),
    EnvVariable(
        "OC_RUNNER_ACTIVE_MODE",
        OPTIONAL,
        "`true`",
        "Runner worker mode: `true` is active, anything else reports `dry_run` (app/main.py).",
        "Active mode.",
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


# Every other variable app/ reads (found by scripts/list_env_reads.py), grouped
# with the reason it is not in the Release 1 checklist. The readiness check
# does not report these. tests/test_release1_env_readiness.py fails when app/
# reads a name that is in neither RELEASE1_ENV nor this appendix.
OTHER_APP_ENV: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Paid model and provider integrations; NO_API_MODE keeps provider calls off for Release 1.",
        (
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "OPENAI_BASE_URL",
            "OPENAI_MODEL",
            "CALYX_AGENT_BASE_URL",
            "CALYX_AGENT_MODEL",
            "CALYX_AGENT_PROVIDER",
            "CALYX_AGENT_TIMEOUT_SECONDS",
            "CALYX_CHAT_API_KEY",
            "CALYX_CHAT_COMPLETIONS_URL",
            "CALYX_CHAT_MAX_TOKENS",
            "CALYX_CHAT_MODEL",
            "CALYX_CHAT_TIMEOUT_SECONDS",
            "CALYX_VISION_ANTHROPIC_MODEL",
            "CALYX_VISION_DURABLE_ENABLED",
            "CALYX_VISION_EPHEMERAL_WRITES_ENABLED",
            "CALYX_VISION_LIVE_INFERENCE_ENABLED",
            "CALYX_VISION_PROVIDER",
        ),
    ),
    (
        "Engineering, GitHub and orchestration automation lanes; not a Release 1 user journey.",
        (
            "CALYX_ENGINEERING_ANTHROPIC_MODEL",
            "CALYX_ENGINEERING_COMPLETION_POLL_SECONDS",
            "CALYX_ENGINEERING_COMPLETION_WORKER_ID",
            "CALYX_ENGINEERING_COMPLETION_WORKER_SECONDS",
            "CALYX_ENGINEERING_ENABLED",
            "CALYX_ENGINEERING_MODE",
            "CALYX_ENGINEERING_PROVIDER_API_KEY",
            "CALYX_ENGINEERING_PROVIDER_MODEL",
            "CALYX_ENGINEERING_PROVIDER_TOKEN",
            "CALYX_ENGINEERING_PROVIDER_URL",
            "CALYX_ENGINEERING_REPOSITORY",
            "CALYX_GITHUB_CODING_AGENT_TOKEN",
            "CALYX_GITHUB_CODING_AUTONOMY_ENABLED",
            "CALYX_GITHUB_CODING_AUTONOMY_OWNER",
            "CALYX_GITHUB_CODING_AUTONOMY_POLL_SECONDS",
            "CALYX_GITHUB_PROPOSAL_EXECUTOR_ENABLED",
            "CALYX_GITHUB_PROPOSAL_EXECUTOR_OWNER",
            "CALYX_GITHUB_PROPOSAL_REPOSITORIES",
            "CALYX_GITHUB_RESEARCH_AUTHORS",
            "CALYX_GITHUB_RESEARCH_BRIDGE_ENABLED",
            "CALYX_GITHUB_RESEARCH_FEEDBACK_TOKEN",
            "CALYX_GITHUB_RESEARCH_LABEL",
            "CALYX_GITHUB_RESEARCH_MAX_PAYLOAD_BYTES",
            "CALYX_GITHUB_RESEARCH_REPOSITORIES",
            "CALYX_GITHUB_RESEARCH_WEBHOOK_SECRET",
            "CALYX_ORCHESTRATOR_ENABLED",
            "CALYX_ORCHESTRATOR_LEASE_SECONDS",
            "CALYX_ORCHESTRATOR_MODE",
            "CALYX_ORCHESTRATOR_POLL_SECONDS",
            "CALYX_OWNER_REVOKED_KEY_IDS",
            "CALYX_OWNER_VERIFY_KEYS_JSON",
            "CALYX_PROGRAM_AUTONOMY_ENABLED",
            "CALYX_PROGRAM_AUTONOMY_LEASE_SECONDS",
            "CALYX_PROGRAM_AUTONOMY_MAX_JOBS_PER_CYCLE",
            "CALYX_PROGRAM_AUTONOMY_OWNER",
            "CALYX_PROGRAM_AUTONOMY_POLL_SECONDS",
            "CALYX_PROGRAM_AUTONOMY_TIMEOUT_SECONDS",
            "CALYX_PROGRAM_AUTONOMY_WORKER_ID",
            "CALYX_SANDBOX_SUPERVISOR_TOKEN_SHA256",
            "CALYX_WORKER_ID",
            "CALYX_DRY_RUN_DIRECTORY",
            "CALYX_ACTIVATION_STATE_PATH",
            "GITHUB_REPOSITORY",
            "GITHUB_TOKEN",
            "GITHUB_WORKSPACE",
        ),
    ),
    (
        "Archive, intake, Google Drive/Gmail and Zenodo pipelines; owner-operated ingestion, not a Release 1 user journey.",
        (
            "ARCHIVE_ALLOWED_ROOTS",
            "ARCHIVE_LEASE_SECONDS",
            "ARCHIVE_LOCAL_WORKERS",
            "ARCHIVE_MAX_FILE_BYTES",
            "ARCHIVE_MAX_PATH_DEPTH",
            "ARCHIVE_MAX_ZIP_EXPANSION_RATIO",
            "ARCHIVE_MAX_ZIP_MEMBERS",
            "ARCHIVE_MAX_ZIP_UNCOMPRESSED_BYTES",
            "CALYX_SCIENTIFIC_ARCHIVE_STAGING",
            "INTAKE_MAX_FILE_BYTES",
            "INTAKE_STORAGE_DIR",
            "GOOGLE_DRIVE_PILOT_FOLDER",
            "GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON",
            "GOOGLE_GMAIL_CREDENTIALS_JSON",
            "GOOGLE_GMAIL_DELEGATED_USER",
            "GOOGLE_GMAIL_SERVICE_ACCOUNT_JSON",
            "CALYX_INTELLIGENCE_GMAIL_QUERY",
            "ZENODO_ACCESS_TOKEN",
            "ZENODO_API_BASE",
            "ZENODO_COMMUNITY",
        ),
    ),
    (
        "Taxonomy intake and activation; owner-gated, not activated in Release 1.",
        (
            "CALYX_TAXONOMY_ACTIVE_BASELINE_PATH",
            "CALYX_TAXONOMY_INTAKE_DIR",
            "CALYX_TAXONOMY_INTAKE_PATH",
            "CALYX_TAXONOMY_MAX_UPLOAD_BYTES",
        ),
    ),
    (
        "Literature, external-source and scientific-pipeline settings; background pipelines, not assessed for this checklist.",
        (
            "BHL_API_KEY",
            "CROSSREF_MAILTO",
            "CALYX_EXTERNAL_LITERATURE_ALWAYS",
            "CALYX_EXTERNAL_LITERATURE_TIMEOUT_SECONDS",
            "CALYX_CLIMATE_TIMEOUT_SECONDS",
            "CALYX_DATA_INTELLIGENCE_ROOT",
            "LITERATURE_EXTRACTION_ROOT",
            "SCIENTIFIC_LANGUAGE_CANDIDATE_ROOT",
            "SCIENTIFIC_LANGUAGE_FIGURE_REQUEST_ROOT",
            "SCI_OBS_EXPORT_ENABLED",
        ),
    ),
    (
        "Surfaces not assessed for this checklist (University, Conservatory storage, reference-document storage, reviewer qualifications, local Show Day rehearsal).",
        (
            "OCU_UNIVERSITY_ENABLED",
            "OCU_UNIVERSITY_LEARNER_AUTH_ENABLED",
            "OCU_UNIVERSITY_RELEASE_EVIDENCE_ID",
            "OCU_UNIVERSITY_SESSION_WRITES_ENABLED",
            "CALYX_CONSERVATORY_DIR",
            "CONSERVATORY_SCAN_BASE_URL",
            "REFERENCE_DOCS_DIR",
            "MISSION_CONTROL_REVIEWER_QUALIFICATIONS_JSON",
            "CALYX_SHOW_CREATE_TABLES",
        ),
    ),
)
OTHER_APP_ENV_NAMES: tuple[str, ...] = tuple(
    n for _, names in OTHER_APP_ENV for n in names
)

# Env reads whose key the static scan cannot resolve, and why each is covered.
UNRESOLVED_ENV_READ_SITES: dict[str, str] = {
    "app/calyx_conversation/interaction_context.py:sanitize_interaction_context": (
        "reads a request mapping named `source`, not the environment"
    ),
    "app/intake/repository.py:get_source": (
        "subscripts a database row named `source`, not the environment"
    ),
    "app/interaction_discovery/service.py:_taxon_matches": (
        "reads a record mapping named `source`, not the environment"
    ),
    "app/main.py:configured": ("generic presence helper that no module in app/ calls"),
    "app/matrix_member_access.py:_positive_int_env": (
        "name comes from _LIMITS; OC_MEMBER_MATRIX_SESSIONS_PER_HOUR and"
        " OC_MEMBER_MATRIX_WRITES_PER_MINUTE are catalogued"
    ),
    "app/release_env.py:_present": "this checklist's own presence check over catalogued names",
}


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
