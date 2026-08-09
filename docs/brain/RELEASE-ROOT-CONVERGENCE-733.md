# RELEASE-ROOT CONVERGENCE — PR #733

Recorded: 2026-08-09
Lane: CI / Release Engineering

## Root — BUILD-615 / PR #733

- Final pre-merge head: `4b91d9db50bd12bd12b359beb341e47ed2ea13e5`
- Parent/base at merge review: `7f5bec2fb8092739a8e5fc5ce55ebc9008a9171e` (`main`)
- Exact-head validation: 12/12 applicable PR workflows completed successfully.
- Final unresolved gate `Calyx Brain Integration` run `31323796634`: SUCCESS.
- Review threads: all resolved; no requested-changes review was present at release verification.
- Merge status: MERGED.
- Canonical merge SHA: `efdd0b02295d4fccf0628ec116552ac41dc76d5c`.
- Merge timestamp: `2026-08-09T16:28:03Z`.
- Scientific/publication authority: UNCHANGED. No publication execution, Candidate Knowledge promotion, production Knowledge Graph mutation, taxonomy activation, deployment, or production migration authorized by this release.

## BUILD-616 canonical successor

Historical stacked PR #740 is superseded and must not be merged.

Canonical current-main successor:
- PR #796 — BUILD-616R
- Base SHA: `fad625655adb974dca44e8abffc538e025739ebd`
- Final head: `745006ee3f783c1bea76c2766e4b37ca6e920b25`
- Merge status: MERGED
- Canonical merge SHA: `46112f1bdfe0ccf724616b9c7925a8652e48c9e2`
- Scientific/publication authority: UNCHANGED; planner remains read-only and non-executing.

## BUILD-617 canonical successor

Historical stacked PR #786 is superseded and must not be merged.

Canonical current-main successor:
- PR #797 — BUILD-617R3
- Base SHA: `46112f1bdfe0ccf724616b9c7925a8652e48c9e2`
- Final head: `54063c08f8efb0ba429272afbb6d9090910a78d0`
- Merge status: MERGED
- Canonical merge SHA: `c89826e808f09555c4662ec03e61d89bdf1f4ebb`
- Scientific/publication authority: UNCHANGED; contradiction accounting remains read-only.

## BUILD-618 release boundary

Historical PR #787 is source material only. Current-main reconstruction is PR #800 — BUILD-618-R3.

At release-boundary inspection:
- PR #800 head: `56daf2ebd7fecfc06ce9949f2c8c6dc80b1e692d`
- PR base snapshot: `3a881b531b39f7f7482d2a8b000a793aaac40a72`
- Canonical main had advanced three commits beyond that base and PR #800 was reported non-mergeable.
- Exact-head workflows were not green; all eight observed applicable runs were `action_required` and produced no executable jobs.
- Three unresolved P1 review threads remained: one stale BUILD-617 regression fixture and two causal-scope normalization/validation defects.
- Advancement therefore STOPPED before BUILD-618 merge. No stale ancestor validation is accepted as authority.

## Canonical contracts preserved

- Candidate Knowledge exact-duplicate identity remains the existing canonical identity contract.
- Knowledge Graph provenance remains serialized under `provenance.source_table`; no competing provenance representation was introduced.
- BUILD-086B retains `MECHANISTIC_RELATIONSHIP_AGGREGATE` in the corrected aggregate-count contract.
- Scientific publication, publication-path expansion, Candidate Knowledge promotion, production Knowledge Graph mutation, taxonomy activation, production migration, and deployment remain unauthorized in this lane.

## Next release action

Reconcile BUILD-618-R3 against current canonical main, address the three demonstrated P1 findings without weakening scientific/governance contracts, obtain a fresh exact head, and require all applicable exact-head checks plus resolved review threads before any BUILD-618 merge. BUILD-619-R2, BUILD-620-R2, and BUILD-621-R2 must not advance until BUILD-618 is canonical.