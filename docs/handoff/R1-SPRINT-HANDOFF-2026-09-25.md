# R1 completion sprint handoff (2026-09-25)

Written from repository state, not recollection. Supersede it at the next session start; don't extend it.

## Heads

| Repo | main | Notes |
|---|---|---|
| orchid-calyx-backend | 1ef29ee | integration `oc-autonomous-integration` @ 8af77bd (synced from main 0be3ebd) |
| orchid-continuum-frontend | 82c76b9 | |
| orchid-continuum-brain | b0e8b2c | agents may not merge here (Brain AGENTS.md:17) |

## Merged this sprint (last 24 h)

**Backend main:**
- #1614: scipy pin derivation
- #1615: interaction-graph docs
- #1616: requires_postgres fails in CI instead of skipping
- #1617: Gary Yong Gee federated ingestion
- #1609: Matrix governed sources on main
- #1611: `GET /api/research/traits`
- #1618: Yong Gee evidence as provisional dossier sections, with distribution, habitat and free-text notes withheld
- #1619: KG evidence-coverage knowledge gaps, fail-closed, replacing the keyword-count generator

**Frontend main:**
- #760, #761: Render gate and ledger
- #765: dossier excerpts
- #764: completion-graph discovery loop; the oc-node label counts as tracking
- #766: Matrix ranking basis, provenance, and the locality-key filter

## Cross-repo path now wired (all read-only, provisional, human review required)

1. Yong Gee workbook → KG evidence nodes (#1617)
2. → species dossier (#1618)
3. → frontend excerpts (#765)
4. → KG evidence-coverage gaps (#1619)
5. → reserve candidates (#1621, open)
6. → `GET /api/runner/knowledge-gaps/reserve-plan` (#1623, open)
7. → frontend client and Portfolio Steward source (#768, open)

Nothing on the frontend calls `planPortfolioSteward` on a schedule yet.

## Open PRs and their state

| PR | Repo | State |
|---|---|---|
| #1621 → integration | backend | gap→reserve adapter; checker defects fixed @39bf783; re-check pending |
| #1623 → integration | backend | reserve-plan endpoint, stacked on #1621; check pending |
| #768 → main | frontend | reserve-plan client; check pending |
| #767 → main | frontend | Research Station evidence chain; checker defects fixed @edcc768; re-check pending |
| #1606 + fix #1620 → #1608 | backend | provider-free edit lane; #1620 re-fixed @a771066 (worktree re-derivation, PEP 503); re-check pending. Merge order: #1620 → #1606 → #1608 into integration |
| #1610 + fix #1622 | backend | **owner-gated**: grants the edit-lane workflow write permissions and replaces a permission-pin test |
| #1605 | backend | **owner**: read the Brain at main instead of the frozen `calyx-core-operational-foundation` ref |
| #1607 | backend | **owner**: lane binding |
| #1199 | backend | **owner**: integration → main promotion |

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

1. Merge on checker PASS: #1620 → #1606 → #1608 into integration; #1621 → #1623 into integration; #767 and #768 into frontend main.
2. Sync main into `oc-autonomous-integration`. It conflicts on the research_traits, matrix_relationship_sources, species_dossier and evidence_coverage files that both sides added. Main's versions are the reviewed ones.
3. Give the frontend a scheduled caller for `planPortfolioSteward`/`admitBackendReservePlan`, through the existing supervisor workflow, no-API and bounded, so KG gaps become oc-prepared issues.
4. Show `item.evidence_state` when it differs from the section state on the species dossier, and drop the double truncation marker (frontend follow-up from the #765 review).
5. Surface `/api/research/traits` (#1611) in the frontend trait explorer against captured payloads. #767 already carries the client.

## First command for the next session

Read this file, then list the open PRs above with `get_check_runs` on each head, and merge only green PRs that have a recorded independent PASS.
