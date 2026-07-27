# BUILD-SEM-001 — Open Questions and Decisions

Questions are ordered by their ability to block implementation.

## Governance and scope

1. Who is accountable for the canonical semantic release: a single ontology steward or a review board?
2. Which changes require two-person scientific review?
3. Is the first governed scheme the historical Illustrated Glossary, a unified Orchid scheme, or several linked schemes?
4. What is the policy for community contributions and disputed meanings?
5. Which source licenses permit redistribution of definitions, images and ontology subsets?

## Identity and compatibility

6. What permanent public domain will own concept URIs?
7. Must identifiers remain resolvable if services or vendors change?
8. Which existing registry/term IDs are already externally referenced?
9. Are existing `canonical_key` values unique beyond a registry and stable enough for aliases only?
10. What compatibility period is required for `/api/ontology`?

## Scientific modeling

11. Which initial concept types and relations are required by real competency questions?
12. How will taxonomic names, taxon concepts and accepted backbone records be separated?
13. Which Plant Ontology, Trait Ontology and Darwin Core releases are authoritative initially?
14. When should a composite trait be modeled locally rather than imported?
15. How will conflicting definitions and ontology mappings be displayed?
16. What evidence threshold permits `exactMatch`?
17. Are horticultural and scientific meanings separate concepts or audience-specific explanations?

## Language and editorial content

18. Which languages and scripts launch first?
19. Who approves preferred labels by language?
20. How are regional common names scoped?
21. Do historical and deprecated terms remain searchable by default?
22. What reading levels/audiences are formally supported?
23. May AI draft explanations, and what review/labeling is mandatory?

## Annotation and literature

24. Which paper formats and repositories must selectors support?
25. How are OCR errors and changing document revisions handled?
26. What auto-accept thresholds, if any, are scientifically defensible?
27. How are abbreviation scope, co-reference, negation and uncertainty represented?
28. Can annotations be exported/imported using the W3C Web Annotation model?

## Search and AI

29. Which query expansions are safe by default, and which require explicit opt-in?
30. How will semantic search relevance be evaluated?
31. Which concept and evidence payload size is acceptable for Calyx grounding?
32. What must Calyx disclose about inference versus retrieved evidence?
33. How are model/provider changes evaluated against a fixed concept-resolution benchmark?
34. Which workbench owns cross-navigation route metadata?

## Media and accessibility

35. Where are master assets and renditions stored?
36. What licenses allow annotation, cropping and derivative educational media?
37. What is the minimum alt-text, caption, transcript and reduced-motion policy?
38. Which 3D formats and selectors are sustainable?
39. Who reviews anatomical accuracy of diagrams, animation and 3D models?
40. How are pronunciations sourced and localized?

## Operations

41. What are release cadence, rollback and deprecation windows?
42. How are external ontology updates diffed and approved?
43. What uptime and latency targets apply to public concept delivery?
44. Can consumers tolerate eventual consistency after a semantic release?
45. Which metrics trigger a release hold?
46. What data must remain private or embargoed?

## Recommended decisions before BUILD-SEM-002

Approve:

- URI namespace and persistence policy;
- initial scheme boundary;
- steward/reviewer roles;
- SKOS JSON profile and external mapping rules;
- first Darwin Core and ontology release pins;
- compatibility commitment for existing APIs;
- one end-to-end pilot corpus and benchmark.

All other questions can be scheduled through later phases if the Phase 1 model retains language, provenance, versioning and extension points.
