# CALYX-472 — Volunteer service, hours, skills, and recognition system

Status: IMPLEMENTED / VALIDATED / PRIVATE OWNER-SCOPED

## Delivered

- Owner-scoped private volunteer profiles with roles, skills, availability, contact data, accessibility/support notes, and explicit privacy level.
- Assignment records with required-skill checks, supervisor reference, conflict annotations, readiness state, and append-style state-transition history with actor/rationale.
- Hour logs that remain `submitted` until a named supervisor verifies them or rejects them for correction; autonomous hour verification is permanently disabled.
- Training records with evidence, review state, and awarded-skill metadata.
- Immutable certificate artifacts registered through the existing Calyx artifact registry with SHA-256 identity and required evidence URIs.
- Recognition records with review provenance and no binding-commitment or public-display authority.
- Conflict disclosures that always enter human review and never constitute an autonomous disciplinary decision.
- Privacy-preserving volunteer export that redacts contact and accessibility/support notes by default and counts only supervisor-verified service hours.
- Mission Control profile, assignment, hour, verification, training, certificate, recognition, conflict, export, and readiness APIs.
- Deterministic nonprofit and orchid-society fixture workflows covering private profiles, supervised service-hour verification, orchid show-table training, certificates, recognition, privacy, owner isolation, and conflict review.
- Record identifiers are validated before filesystem use, preventing path traversal through volunteer, assignment, hour-log, training, certificate, recognition, or conflict identifiers.

## Integration model

CALYX-472 uses the existing owner authentication dependency and existing immutable artifact registry rather than creating competing identity or artifact systems. Certificate registration is evidence-bearing metadata only; it does not make the certificate public or grant external credential authority.

The service is intentionally operational rather than disciplinary. A volunteer can be assigned, trained, credited, recognized, or flagged for human conflict review, but Calyx cannot terminate, punish, publicly expose, or make a binding personnel commitment on behalf of an organization.

## Privacy and governance boundaries

Personal data is private by default. Profile records explicitly set `public_profile_authorized=false`, certificates and recognition set `public_display_authorized=false`, and normal exports redact private contact/support information. Any later public recognition surface would require a separate consent/approval contract.

Hours require supervisor verification and are not credited merely because a volunteer submitted them. Conflict disclosures are review inputs, not disciplinary findings. No autonomous disciplinary action, public personal-data publication, deployment, merge, or binding organizational commitment is authorized by this build.

## Validation

Initial PR validation proved all five nonprofit/orchid-society workflows and permanent governance assertions, then correctly failed Ruff on import formatting in `runtime/volunteer_service.py`. That failure was fixed before expansion; the corrective pass also hardened all filesystem-facing record identifiers.

Exact corrective head `63ce4231c3ae4f987e485ec0962eab4a189a4eae` passed every triggered gate:

- CALYX Volunteer Service 472 run `31262717616` — success: compile, 5 deterministic tests, privacy/human-review assertions, Ruff, and diff hygiene.
- BUILD-088E Validation run `31262717644` — success.
- CALYX Workflow Governance Audit run `31262717666` — success.
- CALYX-SUPERVISED-PILOT-001 run `31262717697` — success.
- CALYX-AUTONOMY-DEPLOYMENT-001 run `31262717701` — success.

The build remains draft/unmerged. No deployment, public personal-data release, binding commitment, or disciplinary decision was performed.
