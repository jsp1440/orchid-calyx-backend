# BUILD-BRAIN-114N — Governed proposal authorization record

## Status

VALIDATED on the merged BUILD-BRAIN-114M-R3 trust root. PR #781 is current with canonical `main`, has `main` as its merge base, and differs only by the six additive 114N files.

## Objective

Add immutable repository-proposal review evidence after BUILD-BRAIN-114M without granting Calyx Git or GitHub mutation authority.

## Current lineage

BUILD-BRAIN-114M-R3 is merged to canonical `main` at `d1735a6a3e0c8fc6749bd4cb8b3dbafdd2716407`. PR #781 was reconstructed on that exact merged trust root with an auditable two-parent commit rather than a force rewrite. Historical #761/#762/#771/#778 lineages are source material only and are not authoritative merge candidates.

## Hardened trust chain

114N accepts only `calyx-git-proposal-manifest-v2`. `ProposalAuthorizationBuilder` accepts no caller-supplied patch receipt. Before producing review evidence it re-resolves the exact durable patch through `PersistedPatchExecutionService`, inheriting the 114M checks over program/job/assignment identity, canonical input checksum, registered executor, output checksum, and requested-patch/output equality.

The authorization layer also revalidates the supplied manifest against the canonical 114M manifest contract rather than trusting a caller-computed digest alone. It verifies schema and digest, repository/base/source/proposed branch identity, bounded canonical changes, non-empty validation evidence, target hashes, exact validation coverage of every proposed change, and canonical manifest reconstruction. A hand-built digest-consistent manifest with empty validations or uncovered changes is rejected.

Each authorization record cryptographically binds the manifest digest, durable `patch_program_job_id`, repository, base commit, source and proposed branches, patch output checksum, producer identity, requester, review class, reviewer identity and roles, decision, rationale, evidence URIs, and decision timestamp.

## Review governance

Only `operational` and `security` review classes are accepted. A reviewer must hold the matching role and must be distinct from both the requester and persisted patch producer. The in-memory registry is immutable per `(manifest_digest, review_class)`: exact replay is idempotent and conflicting replacement fails closed. Review completion requires approved operational and security evidence from two distinct reviewers; any rejection, missing class, or reviewer collision leaves the proposal incomplete.

Even complete review evidence grants no Git mutation, commit, push, PR creation, automatic merge, deployment, publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation authority.

## Failure-first record

FACT — Hosted GitHub runners are currently executing normally. Earlier `action_required` / zero-step incidents were RUNNER/INFRASTRUCTURE evidence and were not treated as application-code failures.

IMPLEMENTED — Review finding on PR #781 identified an authorization-invariant gap: a hand-built manifest with a recomputed digest could bypass stricter 114M proposal-manifest validation. 114N now reconstructs and verifies the canonical manifest contract before issuing review evidence.

VALIDATED — The first repaired head reached executable CI and exposed only Ruff formatter drift; Ruff lint itself passed. Canonical formatter changes were applied without changing the authorization logic.

VALIDATED — The next executable focused run exposed four stale status-test fixtures that still built legacy empty-change/empty-validation manifests. Production validation correctly rejected them with `PROPOSAL_AUTH_CHANGE_COUNT_INVALID`. The fixtures were updated to use a valid covered 114M-style change and validation record; the security gate was not weakened.

VALIDATED — Exact code/test head `b421e8e3356a9fad916fe9d9a8b90a0e883958e6` passed:

- BUILD-BRAIN-114N Proposal Authorization Validation run `31326794000` — success; compile, Ruff, focused authorization/status regressions, non-mutation and persisted-identity assertions, and diff hygiene all passed.
- CALYX-AGENT-003 Validation run `31326794003` — success.
- BUILD-088E Validation run `31326794010` — success.
- CALYX Workflow Governance Audit run `31326794005` — success.

LIMITATION — 114N records review evidence only. It does not provide or activate Git/GitHub mutation transport. Any future live branch/commit/push/PR side-effect capability remains a separate governance boundary.

## Next dependency

BUILD-BRAIN-114P must be rebuilt directly on the merged/validated 114N trust chain before durable reviews, owner authorization, public-key verification, and execution planning can be considered current. Actual Git/GitHub side effects remain a separate explicit governance boundary.
