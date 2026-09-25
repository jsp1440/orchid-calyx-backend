# Autonomous 10-cycle certification

The engineering loop is certified only after ten consecutive accepted cycles.
The evaluator accepts only a positive integer target; booleans, numeric-looking
strings, floats, nulls, and non-positive integers fail closed. It materializes
all supplied evidence and refuses records beyond the target, so an eleventh
record cannot be hidden by returning certification after the first ten.

Cycle identities are the canonical consecutive strings `1` through `10` in
ledger order; unique but skipped, reordered, padded, or descriptive IDs fail.
Each cycle must carry durable work identity and lease identity, an exact PR number
and exact head SHA, exact-head green CI, a merge SHA, independent landed-result
verification, and lease release. Duplicate ownership/lineage, false-green
evidence, abandoned leases, manual intervention, or an unauthorized owner-gate
crossing fails the streak.

The evaluator derives duplicate detection from the persisted evidence itself.
Cycle, work, lease, PR, exact-head, and merge identities must each be unique
across the streak, and commit identities must be complete lowercase 40-character
Git SHAs. Within every cycle, the pre-change verification base, exact PR head,
and persisted merge identity must also be pairwise distinct. Caller-supplied
“no duplicate” assertions are never sufficient.

The JSON ledger can be reconstructed after interruption. Loading fails closed on
unknown schemas, changed targets, malformed cycle shapes, inconsistent derived
acceptance, or a result that does not match the stored evidence. Appending is
atomic; replaying the identical cycle is a no-op, while reusing any durable
identity with changed evidence is refused. Durable string identities must also
be non-empty, unpadded, and printable; whitespace padding and embedded control
characters fail closed instead of creating visually ambiguous identities.

Individual records are insufficient: ledger read and write also validate the
aggregate streak. A duplicate or otherwise rejected cycle cannot be persisted
merely by storing the evaluator's failed result beside it, and evidence beyond
the ten-cycle target is refused instead of silently ignored.

At least one of the ten cycles must encounter a recoverable fault and heal it
without manual intervention. A genuine owner gate parks that item and the
scheduler should select other eligible work; an owner gate is never healed by
bypassing it.

This certification layer is provider-free and evidence-only. It does not grant
merge, deployment, production/scientific mutation, publication, credential,
spending, security, or governance authority.
