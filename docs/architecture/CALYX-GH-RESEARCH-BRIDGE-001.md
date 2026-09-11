# CALYX-GH-RESEARCH-BRIDGE-001

Status: draft, disabled by default, no production activation performed.

## Purpose

This bridge converts an explicitly opted-in GitHub issue into exactly one
existing BUILD-051 Calyx research request. It preserves the originating issue,
author, labels, timestamps, delivery identity, extracted taxa, requested
outputs, and full issue body as provenance-bearing research instructions.

It does not create a second research queue. It does not publish science,
activate taxonomy, mutate the production Knowledge Graph, or disclose
sensitive locality.

## Endpoint

GitHub issues webhook:

    POST /api/integrations/github/research/issues

Protected readiness:

    GET /api/integrations/github/research/readiness

The readiness route requires an owner session or X-API-Key.

## Required configuration

The bridge remains unavailable unless all required values are configured:

- CALYX_GITHUB_RESEARCH_BRIDGE_ENABLED=true
- CALYX_GITHUB_RESEARCH_WEBHOOK_SECRET
- CALYX_GITHUB_RESEARCH_REPOSITORIES
- CALYX_GITHUB_RESEARCH_AUTHORS
- CALYX_GITHUB_RESEARCH_LABEL (defaults to calyx-research)
- DATABASE_URL for durable production persistence

Optional:

- CALYX_GITHUB_RESEARCH_MAX_PAYLOAD_BYTES (default 65536; bounded 1024-524288)
- CALYX_GITHUB_RESEARCH_FEEDBACK_TOKEN

Do not put any secret in an issue, repository file, frontend variable, log,
research request, or result artifact.

Initial safe allowlist:

    CALYX_GITHUB_RESEARCH_REPOSITORIES=jsp1440/Orchid-Continuum-Brain
    CALYX_GITHUB_RESEARCH_AUTHORS=jsp1440
    CALYX_GITHUB_RESEARCH_LABEL=calyx-research

## GitHub webhook configuration

After the draft PR is reviewed, merged, deployed, and environment variables
are configured under separate owner authority:

1. Add a repository webhook to jsp1440/Orchid-Continuum-Brain.
2. Payload URL:
   https://<calyx-backend>/api/integrations/github/research/issues
3. Content type: application/json.
4. Secret: the same server-only value configured as
   CALYX_GITHUB_RESEARCH_WEBHOOK_SECRET.
5. Select only Issues events.
6. Keep the webhook inactive until the readiness endpoint reports configured.
7. Add the calyx-research label to an issue only when it is authorized for
   intake.

GitHub sends X-Hub-Signature-256, X-GitHub-Event, and X-GitHub-Delivery.
The bridge rejects unsigned, invalid, unsupported, untrusted, closed, unlabeled,
malformed, and oversized events.

## Idempotency

The durable request ID is deterministically derived from source repository and
issue number. Re-delivery or a later supported event for the same issue returns
the existing request rather than creating another. Delivery and source revision
digests remain in provenance for audit.

## Feedback

When CALYX_GITHUB_RESEARCH_FEEDBACK_TOKEN is configured, Calyx creates or
updates one marked status comment on the source issue. The marker is stable per
research request, preventing repeated comments. Feedback failure never erases
an accepted research request and returns only a safe error code.

The feedback token must have only the repository issue-comment permission
needed for allowlisted source repositories.

## Current execution boundary

This slice creates the durable request with state:

    queued_waiting_for_executor

That state is intentional. Current main does not provide a verified live
research executor/result-return worker for this intake. The bridge must not
claim the five-orchid literature or Knowledge Graph investigation ran merely
because intake succeeded.

A subsequent governed slice must connect the existing research executor and
artifact registry, then update the same marked issue comment with queued,
running, blocked, and completed states plus evidence artifact identifiers.

## Rollback

Disable without deleting data:

    CALYX_GITHUB_RESEARCH_BRIDGE_ENABLED=false

Then deactivate the GitHub webhook. Existing research requests and provenance
remain available for audit. No production data should be deleted as rollback.
