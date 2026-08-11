-- CALYX-VISION-LEXICON-BRIDGE-001
-- End-to-end schema for Vision → Lexicon → Knowledge-Graph → Figure pipeline.
-- Implements ReferenceImageSet, VisionAnalysis, VisionRegion,
-- CharacterObservation, MorphometricObservation, FigureSpecification,
-- FigureValidationRun, and CharacterConformanceCheck.
--
-- This migration is intentionally not auto-applied.
-- Activation requires the governed migration approval path.
--
-- Scientific safeguards encoded in CHECK constraints:
--   • Uncalibrated morphometrics cannot record absolute physical dimensions.
--   • Color phenotype class is constrained to a closed enumeration;
--     IMAGE_DERIVED is the only class Vision may populate without external evidence.
--   • Review state must follow the approved transition set.
--   • Machine assertion state must remain distinct from reviewed knowledge.

CREATE SCHEMA IF NOT EXISTS oc_vision;

-- ---------------------------------------------------------------------------
-- 1. Reference Image Sets
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS oc_vision.reference_image_sets (
    reference_set_id        UUID PRIMARY KEY,
    title                   TEXT NOT NULL CHECK (length(trim(title)) > 0),
    target_concept_id       UUID REFERENCES oc_concepts.concepts(concept_id),
    taxon_scope             TEXT,
    description             TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by              TEXT NOT NULL,
    review_state            TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (review_state IN ('PENDING','IN_REVIEW','APPROVED','CHANGES_REQUESTED','REJECTED')),
    provenance              JSONB NOT NULL DEFAULT '{}'::jsonb,
    license_summary         TEXT,
    notes                   TEXT
);

CREATE INDEX IF NOT EXISTS ix_oc_vision_ref_sets_concept
    ON oc_vision.reference_image_sets (target_concept_id);
CREATE INDEX IF NOT EXISTS ix_oc_vision_ref_sets_review_state
    ON oc_vision.reference_image_sets (review_state);

-- ---------------------------------------------------------------------------
-- 2. Reference Image Set Items
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS oc_vision.reference_image_set_items (
    reference_set_item_id   UUID PRIMARY KEY,
    reference_set_id        UUID NOT NULL
        REFERENCES oc_vision.reference_image_sets(reference_set_id)
        ON DELETE CASCADE,
    image_id                TEXT NOT NULL CHECK (length(trim(image_id)) > 0),
    media_id                TEXT,
    taxon_id                TEXT,
    taxon_confidence        NUMERIC(4,3) CHECK (taxon_confidence BETWEEN 0 AND 1),
    developmental_stage     TEXT,
    orientation_context     TEXT,
    calibration_status      TEXT NOT NULL DEFAULT 'UNCALIBRATED'
        CHECK (calibration_status IN ('UNCALIBRATED','SCALE_BAR_PRESENT','KNOWN_REFERENCE_OBJECT','RULER_PRESENT','FIELD_CALIBRATED')),
    scale_information       JSONB,
    image_quality_state     TEXT NOT NULL DEFAULT 'UNKNOWN'
        CHECK (image_quality_state IN ('UNKNOWN','ACCEPTABLE','CROPPED','DETACHED_SPECIMEN','LOW_RESOLUTION','OBSTRUCTED')),
    source                  TEXT,
    license                 TEXT,
    provenance              JSONB NOT NULL DEFAULT '{}'::jsonb,
    inclusion_reason        TEXT,
    review_state            TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (review_state IN ('PENDING','IN_REVIEW','APPROVED','CHANGES_REQUESTED','REJECTED')),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_oc_vision_ref_set_items_set
    ON oc_vision.reference_image_set_items (reference_set_id);
CREATE INDEX IF NOT EXISTS ix_oc_vision_ref_set_items_image
    ON oc_vision.reference_image_set_items (image_id);

-- ---------------------------------------------------------------------------
-- 3. Vision Analyses
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS oc_vision.vision_analyses (
    analysis_id             UUID PRIMARY KEY,
    image_id                TEXT NOT NULL CHECK (length(trim(image_id)) > 0),
    content_hash            TEXT NOT NULL CHECK (length(trim(content_hash)) >= 32),
    reference_set_id        UUID REFERENCES oc_vision.reference_image_sets(reference_set_id),
    vision_model            TEXT NOT NULL,
    vision_model_version    TEXT NOT NULL,
    analysis_version        INT NOT NULL DEFAULT 1 CHECK (analysis_version >= 1),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    taxon_context           TEXT,
    taxon_confidence        NUMERIC(4,3) CHECK (taxon_confidence BETWEEN 0 AND 1),
    calibration_state       TEXT NOT NULL DEFAULT 'UNCALIBRATED'
        CHECK (calibration_state IN ('UNCALIBRATED','SCALE_BAR_PRESENT','KNOWN_REFERENCE_OBJECT','RULER_PRESENT','FIELD_CALIBRATED')),
    image_quality           TEXT NOT NULL DEFAULT 'UNKNOWN'
        CHECK (image_quality IN ('UNKNOWN','ACCEPTABLE','CROPPED','DETACHED_SPECIMEN','LOW_RESOLUTION','OBSTRUCTED')),
    analysis_status         TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (analysis_status IN ('PENDING','RUNNING','COMPLETE','FAILED','CANNOT_DETERMINE')),
    review_state            TEXT NOT NULL DEFAULT 'MACHINE_GENERATED'
        CHECK (review_state IN ('MACHINE_GENERATED','COMMUNITY_REVIEWED','EXPERT_REVIEWED',
                                'REVISION_REQUIRED','APPROVED','REJECTED','SCIENTIFIC_APPROVAL_PENDING')),
    provenance              JSONB NOT NULL DEFAULT '{}'::jsonb,
    warnings                TEXT[] NOT NULL DEFAULT '{}',
    limitations             TEXT[] NOT NULL DEFAULT '{}',
    request_hash            TEXT UNIQUE,   -- idempotency key (sha256 of stable input)
    UNIQUE (image_id, vision_model, vision_model_version, analysis_version)
);

CREATE INDEX IF NOT EXISTS ix_oc_vision_analyses_image
    ON oc_vision.vision_analyses (image_id);
CREATE INDEX IF NOT EXISTS ix_oc_vision_analyses_ref_set
    ON oc_vision.vision_analyses (reference_set_id);
CREATE INDEX IF NOT EXISTS ix_oc_vision_analyses_review_state
    ON oc_vision.vision_analyses (review_state);
CREATE INDEX IF NOT EXISTS ix_oc_vision_analyses_request_hash
    ON oc_vision.vision_analyses (request_hash);

-- ---------------------------------------------------------------------------
-- 4. Vision Regions / Structure Observations
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS oc_vision.vision_regions (
    region_id               UUID PRIMARY KEY,
    analysis_id             UUID NOT NULL
        REFERENCES oc_vision.vision_analyses(analysis_id)
        ON DELETE CASCADE,
    concept_id              UUID REFERENCES oc_concepts.concepts(concept_id),
    label                   TEXT NOT NULL,
    bounding_box            JSONB,          -- {x, y, width, height} in image pixels
    segmentation_ref        TEXT,           -- opaque reference to richer mask if available
    landmarks               JSONB,          -- array of {name, x, y} if available
    confidence              NUMERIC(4,3) CHECK (confidence BETWEEN 0 AND 1),
    review_state            TEXT NOT NULL DEFAULT 'MACHINE_GENERATED'
        CHECK (review_state IN ('MACHINE_GENERATED','COMMUNITY_REVIEWED','EXPERT_REVIEWED',
                                'REVISION_REQUIRED','APPROVED','REJECTED','SCIENTIFIC_APPROVAL_PENDING')),
    provenance              JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_oc_vision_regions_analysis
    ON oc_vision.vision_regions (analysis_id);
CREATE INDEX IF NOT EXISTS ix_oc_vision_regions_concept
    ON oc_vision.vision_regions (concept_id);

-- ---------------------------------------------------------------------------
-- 5. Character Observations
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS oc_vision.character_observations (
    observation_id          UUID PRIMARY KEY,
    analysis_id             UUID NOT NULL
        REFERENCES oc_vision.vision_analyses(analysis_id)
        ON DELETE CASCADE,
    region_id               UUID REFERENCES oc_vision.vision_regions(region_id),
    concept_id              UUID REFERENCES oc_concepts.concepts(concept_id),
    character_id            TEXT NOT NULL CHECK (length(trim(character_id)) > 0),
    character_state_id      TEXT,
    numeric_value           NUMERIC,
    unit                    TEXT,
    relative_value          NUMERIC,
    measurement_basis       TEXT NOT NULL DEFAULT 'IMAGE_DERIVED'
        CHECK (measurement_basis IN ('IMAGE_DERIVED','CALIBRATED_SCALE','LITERATURE_REFERENCE',
                                     'RELATIVE_PROPORTION','CANNOT_DETERMINE')),
    confidence              NUMERIC(4,3) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    method                  TEXT,
    evidence_region         TEXT,
    review_state            TEXT NOT NULL DEFAULT 'MACHINE_GENERATED'
        CHECK (review_state IN ('MACHINE_GENERATED','COMMUNITY_REVIEWED','EXPERT_REVIEWED',
                                'REVISION_REQUIRED','APPROVED','REJECTED','SCIENTIFIC_APPROVAL_PENDING')),
    provenance              JSONB NOT NULL DEFAULT '{}'::jsonb,
    limitations             TEXT[] NOT NULL DEFAULT '{}',
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Absolute units only allowed when measurement_basis is CALIBRATED_SCALE
    CONSTRAINT no_absolute_units_without_calibration CHECK (
        unit IS NULL
        OR measurement_basis = 'CALIBRATED_SCALE'
        OR unit IN ('ratio', 'angle_deg', 'angle_rad', 'normalized', 'proportion', 'cannot_determine')
    )
);

CREATE INDEX IF NOT EXISTS ix_oc_vision_char_obs_analysis
    ON oc_vision.character_observations (analysis_id);
CREATE INDEX IF NOT EXISTS ix_oc_vision_char_obs_concept
    ON oc_vision.character_observations (concept_id);
CREATE INDEX IF NOT EXISTS ix_oc_vision_char_obs_character
    ON oc_vision.character_observations (character_id);

-- ---------------------------------------------------------------------------
-- 6. Morphometric Observations
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS oc_vision.morphometric_observations (
    morphometric_id         UUID PRIMARY KEY,
    analysis_id             UUID NOT NULL
        REFERENCES oc_vision.vision_analyses(analysis_id)
        ON DELETE CASCADE,
    region_id               UUID REFERENCES oc_vision.vision_regions(region_id),
    metric_type             TEXT NOT NULL
        CHECK (metric_type IN ('RATIO','NORMALIZED_DISTANCE','ANGLE','SHAPE_DESCRIPTOR',
                               'AREA_RATIO','ORIENTATION_VECTOR','RELATIVE_PROPORTION',
                               'ABSOLUTE_LENGTH','ABSOLUTE_AREA','ABSOLUTE_VOLUME')),
    value                   NUMERIC NOT NULL,
    unit                    TEXT,
    calibration_state       TEXT NOT NULL DEFAULT 'UNCALIBRATED'
        CHECK (calibration_state IN ('UNCALIBRATED','SCALE_BAR_PRESENT','KNOWN_REFERENCE_OBJECT',
                                     'RULER_PRESENT','FIELD_CALIBRATED')),
    calibration_basis       TEXT,
    calibration_uncertainty TEXT,
    confidence              NUMERIC(4,3) CHECK (confidence BETWEEN 0 AND 1),
    landmarks_used          JSONB,
    provenance              JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Absolute physical dimensions require explicit calibration
    CONSTRAINT absolute_dimensions_require_calibration CHECK (
        metric_type NOT IN ('ABSOLUTE_LENGTH','ABSOLUTE_AREA','ABSOLUTE_VOLUME')
        OR calibration_state <> 'UNCALIBRATED'
    )
);

CREATE INDEX IF NOT EXISTS ix_oc_vision_morphometrics_analysis
    ON oc_vision.morphometric_observations (analysis_id);

-- ---------------------------------------------------------------------------
-- 7. Color Phenotype Observations
--    Strict separation: IMAGE_DERIVED vs INFERRED_PIGMENT_CLASS vs CHEMICALLY_VERIFIED
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS oc_vision.color_phenotype_observations (
    color_obs_id            UUID PRIMARY KEY,
    analysis_id             UUID NOT NULL
        REFERENCES oc_vision.vision_analyses(analysis_id)
        ON DELETE CASCADE,
    region_id               UUID REFERENCES oc_vision.vision_regions(region_id),
    phenotype_class         TEXT NOT NULL DEFAULT 'IMAGE_DERIVED'
        CHECK (phenotype_class IN ('IMAGE_DERIVED','INFERRED_PIGMENT_CLASS','CHEMICALLY_VERIFIED')),
    -- IMAGE_DERIVED fields
    rgb_hex                 TEXT CHECK (rgb_hex ~ '^#[0-9A-Fa-f]{6}$' OR rgb_hex IS NULL),
    hsv_hue                 NUMERIC,
    hsv_saturation          NUMERIC,
    hsv_value               NUMERIC,
    lab_l                   NUMERIC,
    lab_a                   NUMERIC,
    lab_b                   NUMERIC,
    pattern_description     TEXT,
    -- INFERRED / VERIFIED pigment fields (only when phenotype_class allows it)
    pigment_class           TEXT,
    pigment_evidence_source TEXT,
    -- Vision alone must NEVER set phenotype_class beyond IMAGE_DERIVED without external evidence
    CONSTRAINT vision_color_class_constraint CHECK (
        phenotype_class = 'IMAGE_DERIVED'
        OR pigment_evidence_source IS NOT NULL
    ),
    provenance              JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_oc_vision_color_obs_analysis
    ON oc_vision.color_phenotype_observations (analysis_id);

-- ---------------------------------------------------------------------------
-- 8. Vision Assertions (machine-derived, provenance-aware, not auto-published)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS oc_vision.vision_assertions (
    assertion_id            UUID PRIMARY KEY,
    analysis_id             UUID NOT NULL
        REFERENCES oc_vision.vision_analyses(analysis_id)
        ON DELETE CASCADE,
    subject                 TEXT NOT NULL,
    predicate               TEXT NOT NULL,
    object_or_value         TEXT NOT NULL,
    evidence_id             TEXT,
    confidence              NUMERIC(4,3) CHECK (confidence BETWEEN 0 AND 1),
    assertion_state         TEXT NOT NULL DEFAULT 'MACHINE_CANDIDATE'
        CHECK (assertion_state IN ('MACHINE_CANDIDATE','COMMUNITY_REVIEWED',
                                   'EXPERT_REVIEWED','APPROVED','REJECTED')),
    review_state            TEXT NOT NULL DEFAULT 'MACHINE_GENERATED'
        CHECK (review_state IN ('MACHINE_GENERATED','COMMUNITY_REVIEWED','EXPERT_REVIEWED',
                                'REVISION_REQUIRED','APPROVED','REJECTED','SCIENTIFIC_APPROVAL_PENDING')),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    provenance              JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS ix_oc_vision_assertions_analysis
    ON oc_vision.vision_assertions (analysis_id);
CREATE INDEX IF NOT EXISTS ix_oc_vision_assertions_subject
    ON oc_vision.vision_assertions (subject, predicate);

-- ---------------------------------------------------------------------------
-- 9. Figure Specifications
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS oc_vision.figure_specifications (
    figure_spec_id          UUID PRIMARY KEY,
    target_concept_id       UUID REFERENCES oc_concepts.concepts(concept_id),
    purpose                 TEXT NOT NULL,
    scope                   TEXT NOT NULL DEFAULT 'MORPHOLOGICAL_ILLUSTRATION',
    taxon_scope             TEXT,
    reference_set_ids       UUID[] NOT NULL DEFAULT '{}',
    required_structures     JSONB NOT NULL DEFAULT '[]'::jsonb,
    required_character_states JSONB NOT NULL DEFAULT '[]'::jsonb,
    required_relationships  JSONB NOT NULL DEFAULT '[]'::jsonb,
    allowed_variation       JSONB NOT NULL DEFAULT '{}'::jsonb,
    excluded_interpretations JSONB NOT NULL DEFAULT '[]'::jsonb,
    relative_geometry_constraints JSONB NOT NULL DEFAULT '{}'::jsonb,
    color_constraints       JSONB NOT NULL DEFAULT '{}'::jsonb,
    literature_constraints  JSONB NOT NULL DEFAULT '[]'::jsonb,
    label_requirements      JSONB NOT NULL DEFAULT '[]'::jsonb,
    uncertainty_notes       TEXT,
    generation_notes        TEXT,
    media_type              TEXT NOT NULL DEFAULT 'STATIC_ILLUSTRATION'
        CHECK (media_type IN ('STATIC_ILLUSTRATION','ANNOTATED_PHOTO','INTERACTIVE_DIAGRAM',
                              'ANIMATION','VIDEO','3D_INTERACTIVE')),
    -- Extended media fields (for animation / video / interactive)
    temporal_sequence       JSONB,
    required_stage_order    JSONB,
    motion_constraints      JSONB,
    duration_range          JSONB,
    loop_behavior           TEXT
        CHECK (loop_behavior IN (NULL,'NONE','LOOP','PING_PONG')),
    scientific_state_transitions JSONB,
    reduced_motion_alternative TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by              TEXT NOT NULL,
    review_state            TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (review_state IN ('PENDING','IN_REVIEW','APPROVED','CHANGES_REQUESTED','REJECTED')),
    version                 INT NOT NULL DEFAULT 1 CHECK (version >= 1),
    provenance              JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS ix_oc_vision_fig_specs_concept
    ON oc_vision.figure_specifications (target_concept_id);
CREATE INDEX IF NOT EXISTS ix_oc_vision_fig_specs_review_state
    ON oc_vision.figure_specifications (review_state);

-- ---------------------------------------------------------------------------
-- 10. Figure Validation Runs
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS oc_vision.figure_validation_runs (
    validation_run_id       UUID PRIMARY KEY,
    asset_id                TEXT NOT NULL CHECK (length(trim(asset_id)) > 0),
    figure_spec_id          UUID REFERENCES oc_vision.figure_specifications(figure_spec_id),
    vision_analysis_id      UUID REFERENCES oc_vision.vision_analyses(analysis_id),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    status                  TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING','RUNNING','COMPLETE','FAILED')),
    overall_review_state    TEXT NOT NULL DEFAULT 'MACHINE_GENERATED'
        CHECK (overall_review_state IN ('MACHINE_GENERATED','COMMUNITY_REVIEWED','EXPERT_REVIEWED',
                                        'REVISION_REQUIRED','APPROVED','REJECTED','SCIENTIFIC_APPROVAL_PENDING')),
    provenance              JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS ix_oc_vision_val_runs_asset
    ON oc_vision.figure_validation_runs (asset_id);
CREATE INDEX IF NOT EXISTS ix_oc_vision_val_runs_spec
    ON oc_vision.figure_validation_runs (figure_spec_id);

-- ---------------------------------------------------------------------------
-- 11. Character Conformance Checks (character-level, inspectable)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS oc_vision.character_conformance_checks (
    check_id                UUID PRIMARY KEY,
    validation_run_id       UUID NOT NULL
        REFERENCES oc_vision.figure_validation_runs(validation_run_id)
        ON DELETE CASCADE,
    character_id            TEXT NOT NULL,
    expected_state_or_range TEXT,
    observed_state_or_value TEXT,
    result                  TEXT NOT NULL
        CHECK (result IN ('PASS','PARTIAL','FAIL','CANNOT_DETERMINE')),
    confidence              NUMERIC(4,3) CHECK (confidence BETWEEN 0 AND 1),
    notes                   TEXT,
    review_state            TEXT NOT NULL DEFAULT 'MACHINE_GENERATED'
        CHECK (review_state IN ('MACHINE_GENERATED','COMMUNITY_REVIEWED','EXPERT_REVIEWED',
                                'REVISION_REQUIRED','APPROVED','REJECTED'))
);

CREATE INDEX IF NOT EXISTS ix_oc_vision_conformance_run
    ON oc_vision.character_conformance_checks (validation_run_id);
CREATE INDEX IF NOT EXISTS ix_oc_vision_conformance_character
    ON oc_vision.character_conformance_checks (character_id);

-- ---------------------------------------------------------------------------
-- 12. Review Records for Vision Pipeline objects
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS oc_vision.vision_review_records (
    review_id               UUID PRIMARY KEY,
    subject_type            TEXT NOT NULL
        CHECK (subject_type IN ('ANALYSIS','REGION','CHARACTER_OBSERVATION','MORPHOMETRIC',
                                'COLOR_OBSERVATION','ASSERTION','FIGURE_SPEC','VALIDATION_RUN',
                                'CONFORMANCE_CHECK','REFERENCE_SET','REFERENCE_SET_ITEM')),
    subject_id              UUID NOT NULL,
    reviewer_id             TEXT NOT NULL,
    reviewer_tier           TEXT NOT NULL DEFAULT 'COMMUNITY'
        CHECK (reviewer_tier IN ('COMMUNITY','EXPERT','SCIENTIFIC_AUTHORITY')),
    review_date             TIMESTAMPTZ NOT NULL DEFAULT now(),
    decision                TEXT NOT NULL
        CHECK (decision IN ('APPROVE','REJECT','REQUEST_REVISION','FLAG_UNCERTAIN')),
    scope_of_expertise      TEXT,
    version_reviewed        INT,
    questions_answered      JSONB NOT NULL DEFAULT '[]'::jsonb,
    comments                TEXT,
    -- Community agreement alone cannot promote to scientific truth
    auto_promotion_blocked  BOOLEAN NOT NULL DEFAULT TRUE,
    provenance              JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS ix_oc_vision_reviews_subject
    ON oc_vision.vision_review_records (subject_type, subject_id);
CREATE INDEX IF NOT EXISTS ix_oc_vision_reviews_reviewer
    ON oc_vision.vision_review_records (reviewer_id, review_date DESC);

COMMENT ON TABLE oc_vision.vision_review_records IS
    'Human review records for vision pipeline objects. auto_promotion_blocked=TRUE '
    'enforces that community agreement alone cannot become scientific truth.';
COMMENT ON TABLE oc_vision.character_observations IS
    'Structured character observations linked to canonical Lexicon concept/character/state IDs. '
    'Absolute units are blocked by constraint unless calibration_state=CALIBRATED_SCALE.';
COMMENT ON TABLE oc_vision.color_phenotype_observations IS
    'Color phenotype records. IMAGE_DERIVED is the only class Vision may populate unilaterally. '
    'INFERRED_PIGMENT_CLASS and CHEMICALLY_VERIFIED require external pigment_evidence_source.';
COMMENT ON TABLE oc_vision.morphometric_observations IS
    'Morphometric records. ABSOLUTE_LENGTH/AREA/VOLUME require non-UNCALIBRATED calibration_state.';
