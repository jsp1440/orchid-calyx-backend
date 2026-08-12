# Trait–Interaction–Genomics: Scientific Hardening

The first operational TIG implementation established the cross-domain architecture linking traits, ecological interactions, molecular/genomic evidence, Neon persistence, and Zenodo archival drafts. The first formal review exposed an important lesson for the scientific design: a system that searches for hidden patterns must be stricter about evidence boundaries than a conventional application feature.

Accordingly, TIG candidate generation now requires a complete three-domain pattern within every contributing taxon. A repeated trait alone, or a trait paired only with an interaction, is scientifically interesting but is not a TIG cross-domain hypothesis. Such partial patterns remain evidence that may support later work; they are not promoted merely because they repeat.

Archive generation follows the same principle. A scientific snapshot must be internally coherent, so Calyx derives the archive result from the dataset on the server and verifies the identity and evidence count before writing a release. Archive paths are confined to the configured staging root and cannot be redirected by dataset identifiers or request-level path overrides.

Zenodo is treated as the long-term versioned scientific archive, but not as an uncontrolled publication target. Calyx may prepare drafts. Public publication remains a human scientific-governance act. Until a durable reviewed-release ledger exists, the backend publication action is disabled and production credentials should not include Zenodo publication scope.

This separation establishes a reusable principle for the Orchid Continuum: computational systems may discover, assemble, score, and prepare; scientific publication requires explicit evidence integrity and review boundaries.
