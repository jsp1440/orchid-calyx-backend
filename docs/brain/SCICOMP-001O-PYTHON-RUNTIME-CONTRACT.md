# SCICOMP-001O — Python runtime contract

## Purpose

Make the repository-side Python interpreter contract explicit before dependency-backed Scientific Computing methods are activated. This removes ambiguity between local/CI assumptions and the runtime version expected by Calyx scientific code.

## Implementation

- root `.python-version` pins Python `3.12.13`;
- read-only `Python Runtime Contract` workflow resolves that version through `actions/setup-python@v6`;
- CI verifies the exact interpreter version rather than accepting a compatible minor version;
- existing base `requirements.txt` is installed under the pinned interpreter;
- `app.main` and `app.routers.calyx_core` are imported;
- `app` and `runtime` are compiled under the pinned interpreter.

## Current-main recovery

The original validated PR #645 became non-mergeable as `main` advanced. This slice rebuilds its two-file runtime contract directly on current `main` and adds this Brain record. The original exact head had passed the runtime contract, workflow-governance, and BUILD-088E lanes; the current-main replacement must pass its own exact-head validation before merge.

## Deployment boundary

This repository contract does not prove the deployed Render service is using Python 3.12.13. A service-level `PYTHON_VERSION` or equivalent hosting override can supersede repository metadata. Production activation of dependency-backed scientific methods therefore still requires deployment-environment verification.

## Governance

This slice adds no SciPy dependency, executes no scientific publication, changes no production flag, performs no deployment, and grants no database, taxonomy, Knowledge Graph, Git, or merge authority to Calyx.
