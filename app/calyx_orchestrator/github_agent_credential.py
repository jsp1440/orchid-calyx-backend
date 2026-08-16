"""The one, sole, dedicated credential path for GitHub coding-agent mutation.

Exists because the codebase already has several *other* GitHub credential
paths, each legitimately scoped to something else - the Brain-config
read-only fetch (`runtime/config_loader.py`, `CALYX_GITHUB_TOKEN` /
`GITHUB_TOKEN`), the read-only repository-inspection connector
(`runtime/connectors/github_connector.py`, same two names), the pre-existing,
separately-certified `calyx_engineering` structured-patch loop
(`app/calyx_engineering/github.py`, `GITHUB_TOKEN` only), and this session's
own harness-level git/PR access (also frequently surfaced as `GITHUB_TOKEN`
or `GH_TOKEN` in a shell environment, entirely unrelated to any of the
above). None of those are ever an acceptable substitute for the GitHub
coding-agent mutation credential - each was scoped, reviewed, and granted
for a different purpose, several of them read-only, one of them a different
mutation pathway entirely with no relationship to the observe/CI/repair
governance built for `GitHubCodingAgentDispatchCycle`.

This module reads exactly one environment variable -
`CALYX_GITHUB_CODING_AGENT_TOKEN` - and nothing else. It does not fall back
to `GITHUB_TOKEN`, `GH_TOKEN`, `CALYX_GITHUB_TOKEN`, or any other name, by
design, not merely by omission: `_load_token` takes the exact variable name
as a required keyword-only parameter specifically so a future edit cannot
quietly widen the lookup by adding an `or os.getenv(...)` fallback without
that being an obvious, deliberate, reviewable change to a single line.
"""
from __future__ import annotations

import os
from collections.abc import Mapping

from .github_proposal_mutation_adapter import RequestsGitHubTransport

CODING_AGENT_TOKEN_ENV_VAR = "CALYX_GITHUB_CODING_AGENT_TOKEN"


class GitHubCodingAgentCredentialError(RuntimeError):
    """Raised when the dedicated coding-agent credential is absent or blank.

    Never includes the attempted value - there is no value to include when
    this fires, by construction: it fires exactly when the lookup found
    nothing usable.
    """


def _load_token(environ: Mapping[str, str], *, variable_name: str) -> str:
    value = (environ.get(variable_name) or "").strip()
    if not value:
        raise GitHubCodingAgentCredentialError(
            f"{variable_name} is not configured. The GitHub coding-agent "
            "mutation path fails closed rather than falling back to any "
            "other credential."
        )
    return value


def load_coding_agent_transport(
    *, environ: Mapping[str, str] | None = None
) -> RequestsGitHubTransport:
    """Builds the transport for exactly one purpose: GitHub coding-agent
    dispatch. Reads only `CALYX_GITHUB_CODING_AGENT_TOKEN`. Raises
    `GitHubCodingAgentCredentialError` - never falls back, never proceeds
    unauthenticated - if that variable is absent or blank.

    `environ` defaults to `os.environ` and exists so callers (and tests) can
    supply an isolated mapping instead of mutating the real process
    environment.
    """
    source = os.environ if environ is None else environ
    token = _load_token(source, variable_name=CODING_AGENT_TOKEN_ENV_VAR)
    return RequestsGitHubTransport(token=token)
