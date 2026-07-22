# BUILD-092 — My Conservatory First Application

## Architecture

BUILD-092 converts the merged BUILD-091 specifications into the first functional My Conservatory frontend. The Vite/React application is an authenticated, responsive single-page application under `client/`. It retains BUILD-091 routes and uses an internal adapter for existing Calyx endpoints instead of adding or imitating the proposed product APIs.

Authentication is fail-closed: an API key or owner bearer session must pass the existing authenticated implementation-planning health endpoint before the adapter reads or writes plant records. Credentials and event context are held only in `sessionStorage`; no secret or collection data is written to persistent browser storage.

## Implemented pages

- Dashboard: real collection totals, QR and identification summaries, recent records, reminders placeholder, quick actions, and navigation cards.
- My Plants: real event-scoped collection records with search, category filtering, deterministic sorting, pagination, table navigation, and empty/error states.
- Plant Detail: real backend fields, QR identifier, notes, category and event metadata, explicit unavailable fields, provenance, citations, scientific uncertainty, and privacy-safe locality.
- Add Plant: accessible validation, duplicate preflight, authenticated persistence through the existing event plant endpoint, error recovery, and success navigation.
- Search: scientific/collection-name and notes search, filtering, sorting, pagination, keyboard navigation, and explicit synonym-data limitations.
- QR Scanner: BarcodeDetector camera flow when supported, manual identifier fallback, identifier decoding, authenticated resolution, and Plant Detail navigation.

Reports, environmental history, bloom history, repot history, reminders, media, exports, and sharing are navigation-complete deferred routes. They clearly identify the future BUILD dependency and never fabricate data.

## Reusable components

Implemented components include Application Shell, Sidebar Navigation, Top Navigation, Orchid Card, Plant Header, Scientific Name Display, Collection Table, Search Field, Search Result Card, Empty State, Loading State, Error State, Pagination, Filter Panel, QR Display, Citation Panel, and Provenance Viewer. Shared components preserve consistent focus behavior, semantics, status messaging, provenance display, and scientific limitations.

## Backend integrations

The adapter uses only existing endpoints:

- `GET /api/implementation-planning/health` for authenticated session/API-key verification.
- `GET /judging/events/{event_id}/plants` for the current real collection dataset.
- `GET /judging/plants/{plant_id}` for detail and QR resolution.
- `POST /judging/events/{event_id}/plants` for real persistence.

The BUILD-091 product endpoints under `/api/conservatory` remain absent. The adapter documents those gaps and supplies no simulated production behavior. Existing backend records do not contain authoritative accepted-name status, synonym assertions, authorship, parentage, photographs, locality, or citations; the UI says so instead of inferring them.

## Accessibility, science, and privacy

The shell provides landmarks, a skip link, visible focus, keyboard-native controls, focus transfer after navigation, text-based uncertainty indicators, semantic tables and headings, responsive layouts, screen-reader status and error messaging, and reduced-motion handling.

Scientific display preserves names exactly as returned, retains uncertainty markers and hybrid notation, never presents a collection name as an accepted name, and keeps provenance beside derived presentation. Locality and unavailable ownership-sensitive fields are restricted by default.

## Validation

BUILD-092 includes 27 Vitest component/domain/page/routing tests plus backend artifact-contract tests. CI runs TypeScript compilation, the Vite production build, ESLint, BUILD-089 through BUILD-091 regression, PostgreSQL 16 validation, Python compileall, Ruff, and `git diff --check`.

## Limitations and BUILD-093 recommendations

- The existing event-scoped judging plant model is a compatibility source, not the complete product collection model.
- Camera QR decoding depends on browser BarcodeDetector support; offline support remains deferred.
- Synonym, accepted-name, parentage, media, locality, citation, and full provenance contracts need the proposed authenticated conservatory endpoints.
- BUILD-093 should implement the approved product collection APIs, server-side search/pagination, taxonomic identity projection, permission-scoped locality/media, and end-to-end browser validation without weakening the adapter’s fail-closed behavior.
