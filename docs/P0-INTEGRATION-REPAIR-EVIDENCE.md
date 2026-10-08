# P0 paired Brain/Calyx integration repair

## Classification and preserved dependencies

CONVERGE, on isolated branch `replit/p0-integration-repair-20261008`.
The branch starts at Calyx #1789, `e0afc3bb1125f60083b2fb0ec43655a2d43989c7`.
Scheduler fixes and the existing timer harness were cherry-picked from #1788;
neither existing PR branch was edited or merged.

Brain companion #223 is pinned at
`ff1d7774b60d5c4a27c15543d255ab1c1f2fa26f`. The additional producer repair is
on `replit/p0-brain-integration-repair-20261008`, with code commits
`7069c42` and `2dcf7dc`. Brain #178 changes the operating-policy JSON;
current companion source already passes the resource-governor policy tests.
Its older branch must not replace the current Brain tree.

The inspected `orchid-continuum-backend` contains data/archives, not a runnable
backend. No replacement service was created there. Current frontend receipt
contracts were checked read-only.

## Actual implementation

- Canonical build replay preserves scheduled/running/completed/cancelled state
  and rejects changed provenance. A deep copy prevents callers mutating the
  saved admission identity.
- The existing authenticated `/programs` API accepts a governed Brain
  verification admission, evaluates the existing constitution, preserves its
  provenance in job inputs, and rejects provider roles, mutation and governed
  publication/deployment/merge/KG requests.
- Brain's real reasoning-contract module produces the API packet directly:
  repository evidence followed by isolated static validation. Source paths and
  SHA-256 hashes are explicit inputs; role mapping is not test-only scaffolding.
- Persistent program admission uses a deterministic owner-scoped UUID and
  existing primary-key arbitration. Simultaneous requests converge on one
  program; conflicting immutable content fails closed. Replays neither create
  duplicate jobs nor restart completed work.
- No schema migration or replacement scheduler was added. Existing worker,
  lease, execution, receipt, recovery and dependency logic remain authoritative.

Production-code repair commit: `6827117`. Focused execution/concurrency evidence
commit: `e917a37`. HTTP-level handoff test commit: `afea6d3`.

## Local evidence only

Six initial replay regressions failed before repair. Subsequent runs recorded:

- 37 admission/build-queue/persisted-worker tests passed.
- 103 focused lifecycle, scheduler, terminal-accounting, worker and race tests
  passed; three checks skipped and one app-import route check deselected.
- 22 later replay/cross-repository/handoff checks passed, including four added
  provenance/provider/mutation/anonymous-authority negatives. The handoff was
  then strengthened to real HTTP and passed again.
- Three opt-in PostgreSQL checks passed: same-identity admission race,
  conflicting admission race, and competing worker claim. Each used its own
  temporary schema on an explicitly supplied loopback disposable database.
- Brain: 64 producer, reasoning, envelope, resource-governor and lane tests
  passed against the actual companion source.
- Changed-file Ruff E4/E7/E9/F, compilation and whitespace checks passed.

The HTTP handoff uses the real producer, request model, route and executors;
only test authentication and the disposable database are substituted. Five
programs contain ten real repository/static checks against isolated source
snapshots of Lexicon, Literature, Research Station, Atlas and University.
Repeating each HTTP packet does not increase program/job counts. All ten jobs
complete, release leases, retain one attempt and durably complete their programs.
This does not certify real authentication providers or scientific workflows.

`artifacts/p0-integration-productive-timer-proof.json` records a new real
PostgreSQL/subprocess timer run: PASS, exactly ten cycles and ten completed
probe jobs, nine assertions, 142.30 seconds. It ran after the production repair
and scheduler convergence, at `9c3dd96`; subsequent changes are tests/evidence.
The timer harness never calls individual cycles itself.

The separate fault/recovery proof in #1788 remains explicitly historical
evidence for duplicate rejection, killed-worker recovery, stale-token fencing,
retries/backoff and dead-letter behavior; it is not relabeled as a new-head run.
Current focused cycle/worker tests also pass.

Example focused commands (run from this checkout):

```sh
NO_API=true DATABASE_URL=sqlite+pysqlite:///:memory: \
OC_BRAIN_CONTRACT_ROOT=/absolute/path/to/brain-integration-repair \
OC_FRONTEND_CONTRACT_ROOT=/absolute/path/to/orchid-continuum-frontend \
python -m pytest -q tests/test_brain_admission_replay.py \
  tests/test_brain_production_handoff.py tests/test_brain_cross_repository_contracts.py

NO_API=true DATABASE_URL=sqlite+pysqlite:///:memory: \
OC_ADMISSION_TEST_DSN=postgresql://oc_test@127.0.0.1:55439/postgres \
python -m pytest -q tests/test_brain_postgres_admission.py
```

PostgreSQL tests refuse a non-loopback/non-proof-port DSN and never use
`DATABASE_URL` to select their PostgreSQL target. Fixture setup initially
omitted an existing foreign-key parent; it was corrected to reuse the existing
orchestrator schema builder. No production database was opened.

## Budget, authorization and publication boundaries

This admission lane has zero external AI-provider capacity: only two existing
provider-free read-only roles are admitted. Packet size, job count, active-job,
lease, timeout and cycle limits remain enforced by existing request/policy
models. No provider authorization or resource-governor spending limit was raised.
Resource-policy tests are not proof of actual subscription usage or balance.

The owner authorized existing Replit credits without a billing-configuration
prerequisite. No credits were purchased and no billing settings changed.
The Agent cannot read live remaining credit usage; no spent/remaining amount
is asserted.

No GitHub-hosted tests or paid providers were invoked. Publication commits
contain `[skip ci]`; no Actions dispatch, bot command or review request is sent.
Skipped hosted checks must not be described as green.

## Recommendation: NO-GO for merge or production activation

GO for paired draft review and local integration testing only.
NO-GO for merging at this stage: independent exact-head review and the paired
dependency/convergence order remain required. No merge is authorized by this
report.

Remaining blockers:

1. Existing discovery clients must supply approved source snapshots and submit
   these packets through their configured authenticated transport. The new
   producer/intake does not silently invent science-to-code mappings or activate
   an unattended production dispatcher.
2. Local source checks and probe cycles are not ten scientific discoveries or
   live product results. Real scientific completion remains separately governed.
3. Hosted scheduling/default-branch activation and deployed cross-repository
   transport are unverified; deployment and hosted test execution were prohibited.
4. Before provider lanes are enabled, actual authorized availability and observed
   usage must be verified. This work authorizes no paid provider use.

## Rollback plan

Before merge: leave/close the new drafts and retain their commits/ZIP; existing
#1788, #1789 and Brain #223 branches are unchanged. Nothing was deployed.

After any separately approved integration: stop the new Brain verification
submission path first, then owner-reviewed revert of this admission/producer
patch pair. Do not delete programs/jobs or reset another agent's branch. No
database migration needs reversal; deterministic IDs are ordinary existing UUID
primary keys, and in-flight programs remain compatible with the existing worker.
Retain the predecessor fixes unless their own separate review directs otherwise.

Use explicit Git commit hashes and the downloadable patch package for rollback;
do not rely on a successful Replit checkpoint.
