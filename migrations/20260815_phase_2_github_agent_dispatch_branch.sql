-- EXECUTOR PREFLIGHT HARDENING, Priority 2
-- Adds the literal branch identity to calyx_github_agent_dispatches, closing
-- the gap documented in Orchid-Continuum-Brain OPS-0008 (issue #973
-- reconciliation: "no dedicated branch field on the dispatch record").
--
-- branch is the authoritative branch reserved for this mission at admission
-- time (CalyxProgramJob.branch / EngineeringAdmissionPolicy's per-branch
-- mutation lock), set once at dispatch creation and immutable thereafter
-- (see DurableGitHubAgentDispatchStore._validate_identity). It is NOT
-- necessarily the actual branch a coding-agent provider creates - the
-- current GitHubCopilotCloudProvider does not report one in advance, since
-- Copilot chooses its own branch name only once it starts work.
--
-- Additive only. Does not activate a worker, credential, merge, or
-- deployment path. NOT applied to any database by this program - see
-- Orchid-Continuum-Brain OPS-0009 for the activation-readiness checklist
-- this remains gated behind.

ALTER TABLE calyx_github_agent_dispatches
    ADD COLUMN IF NOT EXISTS branch VARCHAR(240) NULL;
