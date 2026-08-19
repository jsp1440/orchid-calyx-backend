# CALYX-LEXICON-LIVE-002 — Validation Status

Date: 2026-08-12

## Current release candidates

- Backend PR #896: `CALYX-LEXICON-LIVE-002R — current-main canonical direct entry contract`
- Frontend PR #147: `CALYX-LEXICON-LIVE-002R — full Famous Lexicon on current main`

Both remain Draft and unmerged.

## Current-main integrity

Backend PR #896 was advanced over backend `main` without rewriting the feature history. Current backend main at the integration check was `ab525a851d7bf5b776688649c0c9633f8e343577`; the current-main merge commit on the feature branch is `b37abb50978dacada7f36630a3230384a07d9e33` with the previous feature head and current main as parents.

Comparison from current backend main to `b37abb5097...` is 0 commits behind and contains only the intended CALYX-LEXICON-LIVE-002 files:

1. `.github/workflows/calyx-lexicon-live-002-validation.yml`
2. `app/lexicon/routes.py`
3. `docs/brain/CALYX-LEXICON-LIVE-002.md`
4. `tests/test_calyx_lexicon_live_contract_002.py`

The main-only `docs/.tmp` file is preserved mechanically and is not part of the feature diff.

Frontend PR #147 remains based on current frontend main `7d5d5238af950b26fae3b8e12e4ea493b6bf3442`, is 0 commits behind, and changes exactly the 13 reviewed Lexicon integration files. It does not modify Matrix 013 files.

## Review state

- Backend PR #896: no unresolved inline review threads at the current check.
- Frontend PR #147: no unresolved inline review threads at the current check.
- The six findings repaired on superseded frontend PR #144 remain preserved in #147's identical Lexicon file content, but inherited review history is not treated as a substitute for current-head execution.

## Executable validation boundary

Hosted GitHub Actions is still failing before runner steps are allocated.

Fresh current-head backend runs for `b37abb5097...` were created for CALYX Lexicon Live 002 Validation, Governance, BUILD-088E and Lexicon Intake; the focused Lexicon job completed `failure` with `steps: null` and no logs/executed commands.

Frontend PR #147's Frontend CI was explicitly retried on 2026-08-12. The retry again completed `failure` with `steps: null`; no build, test or lint step executed.

A second execution path was attempted from the available local runtime. `git` is installed, but `gh` is not installed and outbound DNS/network access to `github.com` is blocked, so a repository checkout cannot be obtained there. This is not counted as validation.

Therefore:

- zero-step GitHub failures are infrastructure evidence, not product-test failures;
- no green test/build claim is made;
- no red product-test claim is made;
- both PRs remain Draft/unmerged until trusted executable validation is available.

## Governance remains unchanged

No automatic concept promotion or publication is introduced. Famous/Lovable source material remains presentation/migration input only. Scientific authority remains the ACTIVE + APPROVED Concept Registry. No taxonomy or Knowledge Graph mutation is performed by this release path.
