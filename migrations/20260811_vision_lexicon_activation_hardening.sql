-- CALYX-VISION-ACTIVATION-002
-- Forward-only hardening for the Vision-Lexicon schema before production activation.
--
-- The base migration used the generic figure editorial vocabulary, while the
-- canonical Vision domain creates every machine-derived figure specification
-- in MACHINE_GENERATED state.  This corrective migration aligns the database
-- constraint with the existing governed VisionReviewState vocabulary without
-- granting publication or promotion authority.

DO $$
BEGIN
    IF to_regclass('oc_vision.figure_specifications') IS NOT NULL THEN
        ALTER TABLE oc_vision.figure_specifications
            DROP CONSTRAINT IF EXISTS figure_specifications_review_state_check;

        ALTER TABLE oc_vision.figure_specifications
            ADD CONSTRAINT figure_specifications_review_state_check
            CHECK (
                review_state IN (
                    'MACHINE_GENERATED',
                    'COMMUNITY_REVIEWED',
                    'EXPERT_REVIEWED',
                    'REVISION_REQUIRED',
                    'APPROVED',
                    'REJECTED',
                    'SCIENTIFIC_APPROVAL_PENDING'
                )
            );
    END IF;
END
$$;
