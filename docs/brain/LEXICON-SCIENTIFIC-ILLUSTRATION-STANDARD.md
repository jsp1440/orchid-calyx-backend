# Orchid Botanical Lexicon — Scientific Illustration & Visual Evidence Standard

Status: governing project guidance  
Scope: Illustrated Orchid Lexicon, Vision-Lexicon, scientific figures, species imagery, conceptual diagrams, and related educational assets.

## Purpose

The Lexicon must distinguish **documentary evidence** from **explanatory representation**.

A photograph, specimen scan, microscopy image, or other documentary image records an observed object. An AI-assisted scientific illustration, reconstruction, composite, or conceptual diagram represents a scientific interpretation assembled from evidence. These categories must never be presented as equivalent.

The goal is not to maximize AI-generated imagery. The goal is to provide the **most accurate and useful visual explanation supported by the available evidence**.

## Evidence hierarchy

Prefer, in order appropriate to the question:

1. Correctly identified photographs of real orchids or orchid structures.
2. Specimen, herbarium, microscopy, or other documentary imagery.
3. Existing scientific or historical botanical illustrations with provenance and rights information.
4. Evidence-linked composites or annotated photographs.
5. AI-assisted scientific illustration when authentic imagery cannot adequately isolate, compare, reconstruct, or explain the concept.
6. Conceptual diagrams for mechanisms, sequences, relationships, or processes where literal specimen imagery is insufficient.

This is not a rigid ranking for every use case. The relevant evidence type depends on the scientific question, but synthetic imagery must never substitute for adequate documentary evidence merely because it is visually attractive.

## Species-specific AI reconstruction

When an AI-assisted figure depicts a particular orchid species, the generation specification should be derived from that species rather than from generic orchid appearance.

Where available, use:

- taxonomic descriptions and protologues;
- properly identified photographs from multiple individuals or views;
- herbarium or specimen records;
- diagnostic morphological characters;
- published measurements and proportions;
- microscopy or anatomical references;
- relevant revisionary or monographic literature;
- explicit uncertainty where sources conflict or evidence is incomplete.

A plausible-looking orchid is not sufficient evidence of taxonomic accuracy.

## Process and mechanism figures

Physiological, developmental, ecological, reproductive, and biochemical processes must be researched before illustration.

Examples include:

- photosynthesis and CAM metabolism;
- respiration;
- pollination mechanisms;
- floral development and resupination;
- mycorrhizal germination and nutrient exchange;
- water and nutrient transport;
- velamen function;
- seed development;
- symbiotic or ecological interactions.

Use review literature to establish context when useful, then trace important mechanistic claims to primary literature where practicable. The figure specification must reflect the evidence base, not the image model's general knowledge.

## Required workflow

1. **Define the scientific question.** State exactly what the visual must explain or document.
2. **Select evidence type.** Prefer authentic documentary imagery when it answers the question adequately.
3. **Assemble an evidence package.** Collect literature, descriptions, photographs, specimens, measurements, and diagnostic characters as appropriate.
4. **Extract constraints.** Convert the evidence into explicit structures, relationships, proportions, measurements, character states, labels, and uncertainty notes.
5. **Create the figure specification.** The specification is the scientific authority; the generative system, if used, is a rendering tool.
6. **Render or compose the figure.**
7. **Post-generation comparison.** Compare the resulting visual against the evidence package and document discrepancies and limitations.
8. **Assign provenance and validation state.**
9. **Publish only with clear labeling.**
10. **Advance review state only after the corresponding review actually occurs.**

## Validation states

The preferred public-facing progression is:

**Draft → Evidence-linked → Machine-checked → Expert-reviewed → Validated**

These stages are not interchangeable.

- **Draft** — figure or content exists but may not yet have linked scientific evidence.
- **Evidence-linked** — supporting references and source imagery are recorded.
- **Machine-checked** — automated checks have compared measurable or structured properties with the specification where possible.
- **Expert-reviewed** — a qualified human reviewer has assessed scientific content.
- **Validated** — the figure has passed the required review standard for its intended scientific/educational use.

Community review may supplement these stages but does not automatically equal expert scientific review.

## AI disclosure

AI-assisted figures must be clearly identified and must not be represented as photographs or documentary specimen images.

Preferred public wording:

> AI-assisted scientific illustration based on cited botanical references.

Additional provenance should be available where practical, including reference sources, figure version, evidence class, validation state, known limitations, and reviewer information.

## Measurements and computer vision

Computer vision may be used to examine multiple reference images, identify recurring character states, estimate relative proportions, compare shapes, and perform measurements when scale is valid.

Rules:

- absolute units require valid calibration;
- uncalibrated images support relative measures, ratios, angles, pixels, and shape descriptors only;
- extracted values must retain source-image provenance;
- inferred morphology must remain distinguishable from directly observed morphology;
- model outputs must not silently become scientific observations.

## Scientific uncertainty

Do not force apparent certainty when sources disagree or evidence is incomplete.

The system should record:

- conflicting descriptions;
- variation among specimens;
- uncertain identification;
- incomplete measurement basis;
- alternative mechanisms or hypotheses;
- limitations of the generated figure.

A visually clean illustration must not erase real scientific uncertainty.

## FAQ

### Are all Lexicon images supposed to be AI-generated?
No. Authentic photographs and documentary images are preferred when they communicate the concept accurately. AI-assisted illustration is used when it adds explanatory value that existing imagery cannot provide.

### Can an AI-generated orchid represent a real species?
Yes, but only as an explicitly labeled scientific illustration or reconstruction, not as a photograph. It should be constrained by evidence for that taxon and linked to the sources used.

### Can the model invent missing structures or colors?
No. Unsupported characters must remain unspecified, generalized with an explicit limitation, or marked as uncertain.

### What should happen if photographs disagree?
Record the variation, investigate identification and source quality, and avoid forcing one image into a false universal representation.

### Can a review paper be used for a process diagram?
Yes, particularly for orientation and synthesis, but important mechanistic claims should be traced to primary literature where practicable.

### Is a machine-checked figure scientifically validated?
No. Machine checking is one review layer. Expert review and final validation are separate states.

### Can a conceptual diagram simplify reality?
Yes, if the simplification is scientifically defensible, explicitly presented as conceptual, and does not imply measurements or structures that the evidence does not support.

### How should a real orchid photograph be labeled?
As a photograph or documentary image, with taxon identification, photographer/source, license or rights information, and provenance where available.

### How should an AI-assisted figure be labeled?
At minimum, clearly as AI-assisted. Preferred wording is “AI-assisted scientific illustration based on cited botanical references,” with evidence and validation details accessible to the user.

## Relationship to Orchid Continuum architecture

This standard governs presentation and figure creation but does not create a parallel scientific database.

Canonical authority remains in Orchid Continuum services including:

- Concept Registry;
- Literature and evidence services;
- Vision-Lexicon reference sets and validation;
- Knowledge Graph provenance;
- taxonomy services;
- review and publication governance.

The Lexicon is the human-facing educational and exploratory surface for these governed scientific records.
