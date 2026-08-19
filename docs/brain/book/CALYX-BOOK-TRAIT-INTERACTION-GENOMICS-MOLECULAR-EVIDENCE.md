# Trait–Interaction–Genomics: The Molecular Evidence Gate

The Trait–Interaction–Genomics engine is intended to expose patterns that are difficult to see when phenotype, ecology, and molecular biology are studied separately. Its power depends on refusing an easy but scientifically invalid shortcut: the presence of DNA sequence data is not evidence that a sequence explains a trait.

Calyx therefore separates molecular context from molecular association. Barcode and phylogenetic sequences can help determine lineage, relatedness, and independence. In contrast, the third TIG discovery domain requires evidence that a gene, protein, pathway, marker, expression pattern, or selection signature is actually associated with a phenotype or biological response.

TIG-005 introduces a candidate-and-review architecture for this purpose. Molecular findings extracted from papers or imported from curated resources first enter `oc_genomics.molecular_evidence_candidates`. They carry canonical taxon identity, the trait under study, molecular identifiers, an evidence excerpt, provenance, method, confidence, and review state. They are not immediately visible to the live discovery engine.

Only records explicitly accepted by a human scientific reviewer become visible through the canonical `oc_genomics.trait_associations` or `oc_genomics.expression_associations` views. This creates a durable distinction between a machine-detected possibility and evidence judged adequate for cross-domain analysis.

This is particularly important for the long-term research question behind TIG: whether repeated pollinator pressures are associated with repeated floral traits and repeated molecular features across orchid lineages. A recurrent gene or expression signature across independently evolved pollination systems would be scientifically interesting, but Calyx must still distinguish correlation, selection association, mechanism, and causation. The engine may generate hypotheses; it does not declare causal genes.

The molecular evidence gate therefore turns a current data gap into a research workflow: acquire molecular evidence, normalize identifiers, preserve provenance, review the association, integrate accepted evidence with traits and interactions, correct for phylogenetic non-independence, and only then consider publication or experimental validation.
