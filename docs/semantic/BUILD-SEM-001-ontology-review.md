# BUILD-SEM-001 — Ontology and Standards Review

## Recommendation summary

Adopt a layered standards strategy:

- Darwin Core for biodiversity record interoperability;
- SKOS for concept schemes, labels, definitions, notes, hierarchy, related concepts, and mappings;
- selected domain ontologies for scientific identity;
- RDF as an interchange and projection format;
- OWL only for formally governed axioms;
- PROV-O for interoperable provenance;
- Schema.org for public web discovery.

Do not build a single monolithic Orchid ontology and do not mirror every external ontology term locally.

## Reuse assessment

| Standard/ontology | Recommended use | Do not use it for |
|---|---|---|
| Darwin Core | biodiversity records, occurrences, events, taxa/names, identifications, measurements/facts, attribution | full anatomy, pedagogy, UI vocabulary, reasoning traces |
| Plant Ontology (PO) | plant anatomical entities and plant structure development stages | qualitative trait values or taxonomic names |
| Plant Trait Ontology (TO) | established plant trait concepts and mappings | raw measurements without context |
| PATO | qualities such as shape, color, size and disposition in compositional trait modeling | plant structures themselves |
| Environment Ontology (ENVO) | habitats, environmental features/materials/processes | cultivation instructions or geographic names alone |
| Relations Ontology (RO) | stable relation predicates such as part-of, develops-from and participates-in | ad hoc UI navigation labels |
| Uberon | cross-species anatomy where an appropriate general anatomical concept exists | replacing plant-specific PO coverage |
| Gene Ontology (GO) | biological processes, molecular functions and cellular components when molecular data requires them | visible morphology or horticultural care |
| PROV-O | entity/activity/agent provenance for imports, mappings, definitions and annotations | domain concept hierarchy |
| Schema.org | public concept/media/article markup and discoverability | canonical scientific semantics |
| SKOS | concept schemes, labels, notes, hierarchy, associations and cross-scheme mappings | complex logical restrictions |
| OWL | carefully selected axioms and machine reasoning | every glossary statement |
| RDF | portable identifiers and graph exchange | mandatory internal storage technology |

## Reuse rules

1. Mint an Orchid concept only when no fit-for-purpose external concept exists, when an Orchid-specific editorial concept is needed, or when a stable local aggregation is required.
2. Preserve external identifiers and ontology release versions.
3. Express mappings with explicit predicates and curator status; never infer equivalence from matching labels.
4. `exactMatch` requires semantic interchangeability for the declared scope. Otherwise prefer `closeMatch`, `broadMatch`, `narrowMatch`, or `relatedMatch`.
5. Imported terms remain attributable to their source license and release.
6. Deprecation never reuses identifiers.

## Darwin Core crosswalk

### Natural fit

| Orchid semantic subject | Darwin Core approach |
|---|---|
| taxon/name identity | Taxon class terms such as `taxonID`, `scientificName`, `acceptedNameUsageID`, rank and authorship |
| vernacular name | `vernacularName`, with language supplied by an application profile |
| occurrence and observation context | Occurrence, Event, Location and Identification terms |
| habitat free text | `habitat`; map structured habitat concepts to ENVO in addition |
| associated organisms | `associatedTaxa` for exchange; typed RO/interaction relationships internally |
| trait/measurement exchange | MeasurementOrFact extension or equivalent profile |
| source and attribution | `references`, `bibliographicCitation`, `recordedBy`, `identifiedBy`, institution/collection terms |
| media linkage | `associatedMedia` for simple exchange; richer media metadata outside core |

### Requires an extension/profile

- structured Entity–Quality traits;
- botanical organ and developmental-stage identifiers;
- measurement uncertainty and statistical aggregates;
- pollinator and mycorrhizal interaction roles;
- evidence anchors and claim-level provenance;
- concept-to-concept mappings;
- taxonomic concept circumscriptions;
- region-of-interest annotations in images and 3D models.

### Outside Darwin Core

- audience-specific explanations;
- learning objectives, quizzes and prerequisites;
- hover-card behavior and cross-workbench navigation;
- prompt grounding packages and reasoning traces;
- interactive diagram state;
- media accessibility renditions;
- internal editorial workflow.

## Modeling guidance

Use a compositional pattern for traits:

`bearer entity (PO or taxon)` + `quality (PATO/TO)` + optional `value/unit` + `method` + `life/development stage` + `environment` + `evidence`.

For taxonomic semantics, distinguish:

- nomenclatural name;
- taxon concept/circumscription;
- accepted-use assertion within a source;
- local canonical backbone record.

For botanical structures, prefer PO IDs. For habitat context, prefer ENVO IDs. Use RO predicates where their definitions fit. Cross-ontology reasoning should be limited to approved profiles and tested competency questions.

## Representation profile

The internal API may remain relational JSON. Every concept should nevertheless have a URI and a loss-minimized SKOS/RDF projection:

- concept scheme and concept URI;
- `prefLabel`, `altLabel`, `hiddenLabel` with language tags;
- definition/scope/editorial/history notes;
- broader/narrower/related relations;
- mapping relations;
- provenance and release metadata.

OWL axioms should be maintained in separate governed modules so ordinary editorial changes do not accidentally change inference behavior.

## Risks

- ontology version drift;
- false equivalence from lexical matching;
- license incompatibility;
- over-modeling before user questions are known;
- conflating a taxon with its name;
- treating embeddings as ontology mappings;
- uncontrolled reasoning across external imports.

Mitigation requires release pinning, mapping review, provenance, conformance tests, and reversible projections.
