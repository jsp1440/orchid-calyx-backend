# Orchid Continuum Durable Agent Operating Memory

This file records repeated engineering corrections that must survive individual Claude/Codex/Copilot/Gemini sessions.

It is operational memory, not scientific evidence. Current repository code, schemas, tests, pull requests, workflow results, and explicit owner decisions outrank stale memory.

## Canonical repository identity

- Canonical backend: `jsp1440/orchid-calyx-backend`.
- Canonical frontend: `jsp1440/orchid-continuum-frontend`.
- Do not substitute similarly named legacy repositories when a mission refers to current backend/frontend work.
- `oc-autonomous-integration` is the normal autonomous integration boundary. `main` remains owner-governed unless an explicit owner-approved promotion path says otherwise.

## Repeated correction -> durable rule

When an owner, review, failing test, or verified production observation corrects an agent assumption more than once, do not rely on chat memory. Encode the correction in the smallest durable repository mechanism that will prevent recurrence: this file, `AGENTS.md`, `CLAUDE.md`, a focused test, a contract, or a workflow guard.

Do not create one memory file per trivial edit. Persist only rules that materially prevent repeated cost, scientific error, privacy leakage, branch drift, or governance mistakes.

## CI truthfulness

- A red GitHub Actions badge is not automatically a code failure.
- If a job has no runner and executes zero steps (`runner_id=0`, empty runner name, `steps:null`, or equivalent), classify it as `CI_INFRASTRUCTURE_BLOCKED` / `HOSTED_VALIDATION_UNAVAILABLE`.
- Do not modify working product code in response to a workflow that never executed repository steps.
- Conversely, once a runner is assigned and repository steps execute, treat a deterministic failing step as a real validation failure until reproduced or explained.
- Never claim hosted green evidence when no hosted steps ran.

## Merge integrity

A merge API returning success is not evidence that the merged tree is what an independent checker verified. `expectedHeadSha` constrains which commit is merged, not what a squash produces from it.

In PR #706 the merge succeeded against the verified head and the squash produced a tree three commits behind it. Six regressions landed on the integration branch, one of them a real locality leak, and the lane reported the PR as integrated.

So, for every integration merge:

1. Record the exact independently verified head, before merging. Derive the paths mechanically, from the branch the change forked off -- `git diff --name-status $(git merge-base <verified-head> <base-branch>)..<verified-head>` -- and declare all of them: modified and added as `--path`, removed as `--deleted-path`. Note `<base-branch>`, the branch the pull request targets, and not `<integration-ref>`: after an ordinary merge the verified head is an ancestor of the integration ref, so their merge base is the verified head itself and that range is empty. A hand-picked subset yields a verdict that says nothing about the paths you left out. **Never substitute a path the change did not touch**: it is identical on both sides, so it witnesses nothing, and the tool refuses it.
2. Merge.
3. Immediately inspect the resulting integration tree, from a real checkout, before reporting anything.
4. Prove the verified content is present at every declared path:
   `python3 scripts/oc_verify_merge_landed.py --verified-head <sha> --integration-ref <ref> [--base-ref <pre-merge sha>] --path <p> [--path ...]`
   **The tool derives the path set itself and refuses any other declaration**, so step 1 is how you find out what to type, not a set you curate. Run it, read the `Declare exactly:` list in the refusal, and pass that.
   `--base-ref` is needed ONLY when the verified head is already an ancestor of the integration ref -- an ordinary merge -- because their merge base is then the verified head itself. Pass **the commit the base branch pointed at BEFORE the merge**, not the branch name: after the merge the branch contains the verified head and the tool refuses it. Where the verified head is not an ancestor, `--base-ref` is refused outright: the real merge base is already a pre-change revision, derived rather than named.
5. On a mismatch, stop that merge lane, restore the verified result from the verified head, and report the mismatch. Do not proceed to the next item first.

Exit 0 is the only pass. Exit 2 is an argument or ref the tool refused before comparing anything. Exit 1 is everything else, and it covers three verdicts -- `tree_mismatch`, `evidence_incomplete` and `merge_not_reported` -- so read the printed verdict rather than branching on the code alone.

Never report a pull request as successfully integrated on the strength of the merge API's response alone. The invariant is `app/calyx_orchestrator/merge_integrity.py`; it is pure, deterministic and provider-free, and calling an external model to perform or confirm this check is not permitted.

What it proves, and only this: the integration side holds what was verified, at the paths you declared, including each path's file mode and object type. It says nothing about content the merge added at paths nobody declared.

**Only evidence the merge could have produced is evidence.** Absence is symmetric: two lineages that both lack a file agree about it for reasons that have nothing to do with the merge -- someone else's cherry-pick, a revert, a force-push, a stale `--integration-ref`. So is identity that predates the change: a file the change never touched is the same at the merge base and on both sides. A record made only of deletions, and a record whose paths all match the merge base, each prove exactly as much as an empty record.

So before it compares anything, the tool requires at least one declared `--path` that resolves unambiguously at every pre-change revision and differs from it there. Three things are not that, and each one was once accepted:

* **Absence**, on both sides.
* **Identity that predates the change** -- a file the change never touched.
* **A directory or a gitlink.** `git ls-tree <ref> -- :(literal)src/lib` returns one record, `040000 tree <sha> src/lib`, whose identity changes when a child is DELETED. Declaring a parent directory turned a pure deletion, which the tool refuses outright, into "present" evidence. Entries of type `tree` and `commit` are refused, on `--path` and on `--deleted-path` alike -- the deleted case checked at the pre-change revision, since a deleted path has no entry at the verified head to inspect. A `120000` symlink IS accepted: its blob is the target string, so it compares like any other file. Spell paths exactly as git reports them: a trailing slash matches several entries and resolves to nothing.

**Containment is not evidence.** If the verified head is an ancestor of the integration ref, the COMMIT is in that history and nothing follows about the resulting tree. `git merge -s ours` makes it a parent and lands not one byte; so does `-X ours` on a conflict, and so does a merge followed by a revert. One round of this tool treated containment as sufficient and reported all three as `landed`. The next round added `--base-ref` to fix that, and all three passed AGAIN -- because a caller-named base far enough back makes an untouched path differ from it, and "at least one probative path" let that untouched path stand in for the change.

Ten independent reviews found ten false passes, all one shape: a `landed` verdict reached without comparing anything the merge could have changed. A mistyped path; a dash ref; a deletion needing only absence; a caller-named base; a deletions-only record; a path identical to the merge base; an unresolvable lookup at the base read as a difference; containment treated as sufficient; a directory laundering a deletion into presence; and a caller-named base AGAIN, through the flag added to fix the round before.

Nine fixes each closed a case, and the tenth review found the shape somewhere else every time, because **every one of those false passes was a declaration the operator chose**. Each fix constrained where evidence could come from and left the choosing alone -- in a tool that exists precisely because the operator's choosing is what failed. "At least one probative path" is the premise: it lets a caller pad an honest set, or name a base that makes a dishonest path look honest.

So the rule is no longer a constraint on the declaration. The tool derives the set with `git diff --name-status <pre-change revision>..<verified head>` and refuses anything that is not exactly it.

That makes a base named further BACK than the fork point self-defeating -- it grows the derived set, and every path it adds must be declared and compared. It says nothing about a base named FORWARD of the fork point, which is the eleventh instance: a revision inside the change shrinks the set to the change's tail, and the tool then reports the paths touched before it as paths the change "does not touch". Shrinking is what hides a regression; an earlier version of this paragraph reasoned only about growth and called the family closed.

`--base-ref` is therefore required. The merge base of the verified head and the integration ref cannot stand in for it: every commit of the change is also an ancestor of the verified head, so when the integration ref descends from a commit inside the change -- **a branch merged from behind its head, which is how PRs in this repository have actually been landing** -- that merge base is inside the change too.

What the tool still cannot do is check that the ref you name IS the fork point. A commit inside the change and the fork point are both ancestors of the verified head and nothing distinguishes them; refusing every ancestor is not the answer either, because a base branch that has not moved since the fork is one. **Derive `--base-ref` from the pull request's own base branch, mechanically. Do not pick a commit.** This is the one input the tool cannot enforce that rule for.

When a fix keeps failing in the same shape, the defect is in the premise the fix preserves, not in the case it closed. Twice a fix's own refusal message became the next delivery vector, telling the operator to do the thing that manufactures the pass. Twice the fix for a false REFUSAL became the next false PASS: widening a gate to admit an honest case admitted the dishonest ones with it. **A caller-named base was listed here as closed while a later round reintroduced it** -- so check this list against the code, not against its own history.

A coverage note believed instead of executed is the same failure wearing a different hat. The seventh instance was unreachable-by-inspection for exactly as long as a test docstring asserted that `:(literal)` made a multi-match impossible; it does not, and nobody ran the mutation that would have said so. Claim a guard is covered only after watching the named test go red without it, and count survivors from that run, not from reading.

Absence is not evidence, and a fact the caller supplies is not a check. If you find yourself declaring a path, or naming a ref, to make a check go green, you are manufacturing the failure this rule exists to prevent.

## Stuck-repair protection

After three unsuccessful attempts on the same deterministic failure class, stop speculative repair commits. Read the exact failing output, run the exact formatter/linter/test command locally where possible, compare it with workflow behavior, and make one deliberate correction. If accumulated branch churn obscures intent, reconstruct cleanly from current integration and preserve only intentional changes.

## Convergence before expansion

- Reuse the authoritative open PR for an acceptance criterion instead of starting a parallel lineage.
- If a producer/consumer pair is being converged, stabilize and validate the producer contract before expanding the consumer.
- Waiting for CI on one lane is not permission to open an unrelated foundation initiative when another existing executable convergence task is available.
- A blocked task parks that task, not the whole program.

## Scientific and privacy trust boundaries

- Generic genus navigation context is identity/navigation context, not evidence.
- For governed generic-genus arrivals, scientific evidence, confidence, conclusion, provenance, locality, coordinates, occurrence IDs, project IDs, exact-taxon IDs, or similar contaminating fields must fail closed when the governing contract says they are forbidden; do not silently broaden or reinterpret the scientific subject.
- Protected locality and private Conservatory information must never leak into public route/query context.
- Grower observations, photographs, measurements, collection locations, and cultivation history are not scientific evidence merely because they are attached to a taxon.
- `UNKNOWN`, `UNAVAILABLE`, `WITHHELD`, `ABSENT`, `CONTRADICTORY`, `REJECTED`, `SUPERSEDED`, `PROVISIONAL`, and `VERIFIED` are distinct states. Do not collapse them to simplify UI or scoring.

## Orchid naming / partnership language

- Do not imply a formal NAOCC/Smithsonian partnership unless the owner explicitly confirms and authorizes that claim.
- Neutral continuity/demo/test naming is preferred unless a partner relationship is actually established.

## Owner interaction

The owner is not a prompt relay, branch coordinator, or CI monitor. Agents should inspect GitHub state directly and leave durable comments/PR evidence.

Ask the owner only for genuine authority, credentials/private inputs, scientific policy, spending, production deployment/publication, or another decision that cannot be derived from repository truth.

## Engineering Memory boundary

Engineering Memory and this operating-memory file are non-scientific operational context. They may guide coding work but may never be cited or promoted as scientific evidence, taxonomic authority, occurrence evidence, or cultivation evidence.

## Autonomous continuation

Completing one bounded PR or test suite is not the same as completing a multi-step mission. If the linked acceptance criterion still has safe executable work, record the completed slice and continue to the next missing slice or let the coordinator immediately dispatch it. Do not voluntarily stop merely because the narrative for one subtask feels complete.

Owner/security/production gates remain hard stop points for the gated action only.
