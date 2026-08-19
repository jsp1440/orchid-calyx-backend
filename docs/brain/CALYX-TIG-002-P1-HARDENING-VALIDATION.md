# CALYX-TIG-002 Validation Plan

Validation for this hardening branch is intentionally bounded to the TIG subsystem plus startup/import and repository-wide checks already configured in GitHub Actions.

Required focused checks:

- `pytest -q tests/test_trait_genomics_discovery.py tests/test_trait_genomics_hardening.py`
- import/compile validation for `app.trait_genomics`
- Ruff/static validation on changed Python files
- `git diff --check`

Merge criteria:

- focused TIG regression tests pass;
- GitHub Actions runs triggered for the pull request complete successfully or any unrelated infrastructure failure is separately identified;
- no unresolved P1 scientific-integrity or publication-governance review findings remain.
