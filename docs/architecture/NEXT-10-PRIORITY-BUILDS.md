# Next 10 Priority Builds

Approved implementation order following BUILD-BRAIN-107.

1. **BUILD-BRAIN-108** — Governed executor adapter and dry-run execution boundary — issue #426.
2. **BUILD-BRAIN-109** — Execution leases, heartbeats, timeout, and recovery — issue #427.
3. **BUILD-BRAIN-110** — Dependency-aware scheduler and critical-path ordering — issue #428.
4. **BUILD-BRAIN-111** — Evidence and artifact registry — issue #429.
5. **BUILD-BRAIN-112** — Human review, approval gates, and release eligibility — issue #430.
6. **BUILD-BRAIN-113** — Automatic Brain capture from execution receipts — issue #431.
7. **BUILD-MC-200** — Mission Control orchestration API and portfolio projection — issue #432.
8. **BUILD-KE-300** — Knowledge Explorer engineer activation and velamen vertical slice — issue #433.
9. **BUILD-FIG-301** — FigureLabs assisted gateway and scientific plate ingestion — issue #434.
10. **BUILD-ATLAS-400** — Atlas engineer activation and thematic-map execution slice — issue #435.

## Dependency sequence

`108 → 109 → 110`

`107 → 111 → 112 → 113`

`110 + 113 → MC-200`

`MC-200 + 112 → KE-300 → FIG-301`

`MC-200 + existing Atlas PR #420 → ATLAS-400`

## Standing safeguards

- no autonomous merge;
- no autonomous deployment;
- no autonomous scientific publication;
- no direct production Knowledge Graph mutation;
- preserve provenance;
- separate evidence from inference;
- deterministic outputs and checksums;
- human review remains mandatory where scientific, licensing, security, or release approval is required.

## Current status

BUILD-BRAIN-108 is active on draft PR #425. The dry-run executor boundary and focused tests have been committed. Builds 109–117 are filed and ordered but not claimed complete.