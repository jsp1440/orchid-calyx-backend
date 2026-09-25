# R1 completion sprint handoff (2026-09-25)

Written from repository state, not recollection. Supersede it at the next session start; don't extend it.

## Heads (updated 2026-09-25 ~16:15 UTC)

| Repo | main | Notes |
|---|---|---|
| orchid-calyx-backend | 64a8bfe | integration `oc-autonomous-integration` @ b067f2e (main synced via #1624; #1621, #1623 merged) |
| orchid-continuum-frontend | 6740659 | #767, #773 merged |
| orchid-continuum-brain | b0e8b2c | agents may not merge here (Brain AGENTS.md:17) |

## Merged this sprint

- **Backend main:**
  - #1614–#1619 (#1618: Yong Gee in the dossier, with distribution, habitat and free-text notes withheld; #1619: KG evidence-coverage gaps)
  - #1609: Matrix governed sources
  - #1611: `/api/research/traits`
  - #1625: main lint debt and CI-sensitive tests
- **Backend integration:**
  - #1606 + #1620: provider-free edit lane, with fixed receipts and PEP 503
  - #1608: production-import check
  - #1624: main sync
  - #1621: evidence-gap reserve candidates, canonical taxon names only
  - #1623: `GET /api/runner/knowledge-gaps/reserve-plan`
- **Frontend main:**
  - #760, #761, #765
  - #764: graph discovery loop
  - #766: Matrix ranking basis and locality filter
  - #768: backend reserve-plan client
  - #772: dossier item evidence state and a single truncation marker
  - #767: Research Station evidence chain
  - #773: opt-in supervisor admission of the reserve plan (off until `OC_ADMIT_BACKEND_RESERVE=1`)

## Cross-repo path (read-only, provisional, human review required)

1. Yong Gee workbook → KG evidence nodes (#1617)
2. → species dossier (#1618)
3. → frontend excerpts (#765, #772)
4. → KG evidence-coverage gaps (#1619)
5. → reserve candidates using canonical taxon names only (#1621, integration)
6. → `GET /api/runner/knowledge-gaps/reserve-plan` (#1623, integration)
7. → frontend client (#768, merged)
8. → opt-in supervisor admission, `OC_ADMIT_BACKEND_RESERVE=1` (#773, merged, off by default)

## Open PRs

| PR | Repo | State |
|---|---|---|
| #1610 + #1622 | backend | **owner-gated**: edit-lane workflow write permissions |
| #1605, #1607, #1199 | backend | **owner** decisions: Brain ref, lane binding, integration → main. #1199 now also carries #1606/#1608/#1621/#1623, since the backend reserve-plan endpoint lives only on integration until it is promoted. |

## Owner gates (nothing else is blocked on the owner)

- **Brain:**
  - merge #159 → #161 → #163, then #162;
  - close #164 unmerged (it is a proof PR).
- **Backend:** #1605, #1607, #1199, #1610/#1622; set `OC_DONE_GUARD_APPLY` if the oc-done guard should act rather than report.
- **Render:**
  - `DATABASE_URL` on the Calyx service (the dossier, the gaps and the reserve plan fail closed without it);
  - the build installs `requirements-scientific.txt`;
  - the frontend `VITE_CALYX_API_URL` if the origin is not `https://orchid-calyx-backend.onrender.com`.
- **Data and policy:**
  - regenerate `runtime/knowledge_gaps/latest.json` through an owner-authorised `POST` discover against the production KG;
  - a locality-sensitivity review before Yong Gee taxon_notes/compiler_note, distribution or habitat can be shown;
  - CRM subscribe (PII and consent);
  - #723 vs #757;
  - the Brain Copilot drafts;
  - the Hassler lifecycle producer (#1574 vs #1116);
  - the oc-node/oc-cap label list for existing issues.

## Next 5 tasks, in priority order

1. Owner: promote integration → main (#1199), so the Render backend serves `/api/runner/knowledge-gaps/reserve-plan`; then set `DATABASE_URL` on the Calyx Render service.
2. Owner: set `OC_ADMIT_BACKEND_RESERVE: '1'` in the frontend supervisor step so KG evidence gaps become oc-prepared research issues. It is capped at 3 per pass and fails closed.
3. Owner: merge the Brain PRs #159 → #161 → #163 and #162; decide #1605, reading the Brain at main.
4. Run the locality-sensitivity review so Yong Gee taxon_notes can be shown on the dossier.
5. Surface `/api/research/traits` (backend main) in the frontend trait explorer.

## First command for the next session

Read this file, then list the open PRs above with `get_check_runs` on each head, and merge only green PRs that have a recorded independent PASS.
