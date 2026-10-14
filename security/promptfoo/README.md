# Offline red team: direct-executor tool guards

Isolated security suite for `scripts/swarm_anthropic_direct.py`. It needs no model, no network and no credentials, and writes nothing outside a throwaway sandbox.

## What it tests

A coding model can be talked into a harmful tool call by prompt injection, whether in issue text, PR comments, repository files or tool output. The model cannot be relied on to refuse, so the executor's deterministic tool layer is the actual boundary.

Each case is one tool call a compromised model might make. It runs against the real handlers, inside a temporary repository that contains:
- decoy secrets;
- governance files;
- a symlink pointing outside the sandbox.

`run_check` commands are recorded, never executed.

| File | Purpose |
|---|---|
| `cases.yaml` | Enforced cases and their required verdicts (`REFUSED` / `ALLOWED` / `EXECUTED`). |
| `gaps.yaml` | Open findings: cases the executor does not yet meet. |
| `oc_guard_harness.py` | Runs a case in the sandbox. Shared by pytest and Promptfoo. |
| `provider.py` | Promptfoo custom provider wrapping the harness. |
| `build_config.py` | Generates `promptfooconfig.yaml` from `cases.yaml`. |

## Running

CI runs `pytest tests/test_oc_promptfoo_security_cases.py`, with no Node required. It enforces `cases.yaml` and runs `gaps.yaml` as strict xfail, so closing a gap turns the suite red until that case moves to `cases.yaml`.

Through Promptfoo, with a pinned version and telemetry, update checks and sharing off:

```bash
cd security/promptfoo
PROMPTFOO_DISABLE_TELEMETRY=1 PROMPTFOO_DISABLE_UPDATE=1 PROMPTFOO_DISABLE_SHARING=1 \
PROMPTFOO_PYTHON="$(which python3)" \
npx -y promptfoo@0.123.1 eval -c promptfooconfig.yaml --no-cache --no-write
```

After editing `cases.yaml`, regenerate the config with `python build_config.py`. A test fails if the two drift apart.

## Findings closed in the executor

| Finding | Gap (before) | Enforcement now |
|---|---|---|
| OC-SEC-EXEC-001 | `read_file` and `search_text` could read `.env` and `*secrets.json`. | Credential files (`.env`, `.env.*`, `secrets.json`, `*-/_/.secrets.json`) are neither read, searched, written nor named as a check target. Checks use the resolved path, so symlinks are covered. Secret-free templates (`.env.example`, `.env.sample`, `.env.template`, `.env.dist`) stay readable. |
| OC-SEC-EXEC-002 | `AGENTS.md`, `CLAUDE.md` and `.claude/**` were writable. | Every restricted path in `docs/AGENT-SECURITY-BOUNDARIES.md` is read-only to the executor; changes go through an owner-reviewed PR. `docs/AGENT-OPERATING-MEMORY.md` is not a restricted path and stays writable. |
| OC-SEC-EXEC-003 | Found while closing 001: `search_text` followed a *file* symlink out of the repository and returned its contents. | Searched files must resolve inside the repository. |

Run against the previous executor, 18 of these cases fail. After the fix all pass. `gaps.yaml` is empty.

## Not in scope

This suite has no model-in-the-loop prompt-injection red teaming. That would make provider calls, so it falls under NO_API_MODE and the governor budget, and would need separate authorization.
