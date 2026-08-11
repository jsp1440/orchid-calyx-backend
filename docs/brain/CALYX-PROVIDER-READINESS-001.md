# CALYX-PROVIDER-READINESS-001 — Conversational provider truth and acceptance lifecycle

## Status

Implemented on backend PR #876, targeting the pending `CALYX-SPEAK-005-WORKSPACE-OUTPUTS` release line in PR #873. Frontend truth-state presentation is implemented on frontend PR #138, intentionally stacked after the adaptive Matrix workspace PR #136.

The production live-acceptance harness remains validation-only in backend PR #867 and is not itself product functionality.

## Problem

Speak with Calyx has two materially different runtime modes:

1. a configured OpenAI-compatible generative conversational provider; and
2. `deterministic-governed`, the safe fallback that formats governed retrieval/Brain outputs without inventing unsupported scientific claims.

Both are useful, but they are not equivalent. A deterministic fallback must never be presented as if a generative scientific collaborator has passed live conversational acceptance. Likewise, merely setting a provider endpoint and model does not prove that the deployed provider actually works or that its scientific conversation behavior has been accepted.

## Authenticated readiness contract

`GET /api/calyx/speak/status` exposes a secret-safe `reply_provider` block containing:

- `mode`
- `generative_configured`
- `model`
- `endpoint_configured`
- `live_acceptance_verified`
- `acceptance_attestation_matches_runtime`
- `accepted_speak_release`
- `fallback_mode`

The status response does not expose `CALYX_CHAT_COMPLETIONS_URL` or `CALYX_CHAT_API_KEY`.

## Configuration versus acceptance

Generative configuration requires both:

- `CALYX_CHAT_COMPLETIONS_URL`
- `CALYX_CHAT_MODEL`

If either is missing, runtime readiness reports the deterministic governed fallback.

Live acceptance is a stricter state. It requires all of the following deployment attestations:

- `CALYX_CHAT_LIVE_ACCEPTANCE_VERIFIED` truthy;
- `CALYX_CHAT_LIVE_ACCEPTANCE_MODEL` exactly equal to the currently configured `CALYX_CHAT_MODEL`;
- `CALYX_CHAT_LIVE_ACCEPTANCE_RELEASE` exactly equal to `CALYX-SPEAK-005-WORKSPACE-OUTPUTS`.

Therefore a stale acceptance cannot silently survive either a model change or a Speak release change. Any mismatch forces `live_acceptance_verified = false`.

The attestation values are not themselves a substitute for running the acceptance harness. They are deployment-state records that should be set only after the protected live acceptance has passed for that exact model/release combination.

## Live acceptance harness

Backend PR #867 contains the protected production acceptance workflow and `scripts/smoke_calyx_speak_live.py`.

The harness now:

- authenticates exactly like the browser through the HttpOnly owner-session cookie;
- accepts current `CALYX-SPEAK-004-CONTEXT` and pending `CALYX-SPEAK-005-WORKSPACE-OUTPUTS`, while rejecting older/stale Speak releases;
- reads provider readiness when available and fails before running the five-turn dialogue if the deployment explicitly reports non-generative mode;
- creates one server-owned conversation;
- runs the five-turn Calyx Vision requirements dialogue in the same thread;
- forces governed research mode on the substantive Vision turns;
- records provider and model for every turn;
- fails if any substantive Vision turn falls back to `deterministic-governed`;
- requires one stable reported model across substantive turns;
- restores the server transcript and checks that the conversation persisted;
- checks for expected epistemic/visual content markers in the substantive dialogue;
- performs no publication, Candidate Knowledge promotion, taxonomy activation, or Knowledge Graph mutation.

The previous harness expectation for `CALYX-SPEAK-003` was stale and would have failed against healthy current production. That defect was repaired on PR #867.

## Frontend truth state

Frontend PR #138 implements a shared provider-mode presentation with four fail-closed states:

- accepted generative;
- generative provider configured, live acceptance pending;
- deterministic governed fallback;
- provider status unavailable.

The Illustrated Orchid Lexicon and Matrix Identification conversation surfaces use the same badge. The lexicon header no longer says `Live governed conversation`; it now says `Governed conversation service`, with the actual runtime mode shown separately.

The primary `/calyx` workspace still needs the same badge insertion. That page is currently a large monolithic component, so the insertion is being held rather than performing a high-risk whole-file rewrite while trusted CI is unavailable.

## Governance boundaries

This work does not:

- configure or purchase a model provider;
- spend provider credits;
- claim that production acceptance has passed;
- publish scientific knowledge;
- promote Candidate Knowledge;
- mutate the Knowledge Graph;
- activate taxonomy;
- release Figure Labs generation.

The live Calyx Vision self-requirements conversation remains incomplete until the deployed runtime actually uses a non-deterministic generative provider and the protected acceptance dialogue passes.

## Validation blocker

GitHub-hosted Actions are still refusing runner allocation because of the account billing/spending-limit condition. The provider-readiness tests, frontend presentation tests, and production acceptance harness are committed, but none should be represented as hosted-CI validated until a trusted runner is restored.

## Ordered release path

1. Restore a trusted validation path without silently changing billing.
2. Validate/merge backend #873 (`CALYX-SPEAK-005-WORKSPACE-OUTPUTS`).
3. Validate/merge backend #876 (provider readiness) and backend #874 (Matrix workspace output) in dependency-safe order.
4. Validate/merge frontend #134, #135, #136, and #138 in dependency order.
5. Deploy the exact accepted backend/frontend heads.
6. Configure the generative provider if it is not already configured.
7. Run protected production acceptance PR #867 against the deployed runtime.
8. Only after a successful run, record matching model/release acceptance attestations.
9. Complete and review the actual Calyx Vision requirements dialogue.
10. Only then resume the held Figure Labs / Vision illustration blueprint and generation decisions.
