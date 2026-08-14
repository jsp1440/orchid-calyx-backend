# CALYX-INTEL-005R — Twin Gmail Read-Only Collector on Current Main

Status: **IMPLEMENTED / VALIDATION IN PROGRESS / LIVE CREDENTIAL ACTIVATION NOT AUTHORIZED**

## Purpose

CALYX-INTEL-005R forward-ports the validated Twin → Calyx Gmail intake slice from historical PR #938 onto current canonical backend main without restoring stale application code.

The objective is to let Calyx ingest matching Orchid Continuum Daily Briefing emails directly from Gmail through a narrowly scoped read-only gateway and feed them into the canonical intelligence-assimilation path with source provenance intact.

## Current-main reconstruction

Reconstruction branch: `feature/calyx-intel-twin-gmail-current-main-v2`.

Historical source: PR #938 / branch `agent/calyx-twin-gmail-collector`.

Current-main overlap was checked before transplant. Of the seven forward-ported paths, only `app/intake/routes.py` existed in the historical merge-base and current main; current main had not modified that path after the merge-base. The remaining six paths were absent from current main. Exact reviewed Git blobs were therefore transplanted without overwriting later intelligence, Matrix, Vision, conversation, harvester, or persistence work.

## Implemented behavior

The slice provides:

- Gmail API list/get gateway only;
- default Gmail query narrowed to `from:twin@twin-mail.com` and subject `Orchid Continuum Daily Briefing`;
- exact sender and subject validation after Gmail search;
- preservation of Gmail message ID, Internet Message-ID, sender, subject, received timestamp, and source context;
- MIME plain-text / HTML extraction;
- HTTP(S) source-link preservation for links present only in HTML, including Twin `View Source` anchors;
- duplicate-link suppression and exclusion of non-HTTP schemes;
- bounded per-message failure isolation;
- shared provenance-preserving email application service;
- ingestion through the canonical intelligence assimilation service rather than direct canonical Knowledge Graph writes;
- explicit receipts declaring mailbox mutation, canonical-graph mutation, and external contact as false.

## Mailbox safety contract

The Gmail gateway exposes only `users.messages.list` and `users.messages.get` semantics. It does not implement send, reply, forward, modify, archive, trash, delete, label mutation, mark-read, or mailbox-state mutation.

No Gmail credential is stored in this repository. The implementation does not broaden OAuth scope and does not fabricate a production credential source.

## Scientific-governance contract

Twin emails are external secondary intelligence, not canonical scientific truth. Intake may create governed intelligence records for later verification, but it does not by itself:

- promote Candidate Knowledge;
- publish scientific claims;
- alter taxonomy;
- mutate the production Knowledge Graph;
- contact external partners;
- disclose restricted locality data.

## Validation

Dedicated validation is provided by `.github/workflows/calyx-twin-gmail-collector-validation.yml` and focused tests:

- `tests/test_twin_gmail_collector.py`;
- `tests/test_intelligence_html_links.py`.

The pull request also triggers adjacent intake/database/governance validation on current main. Exact-head workflow results must be green before merge.

## Activation boundary

Live unattended Gmail acquisition remains a separate governed runtime step. It requires an explicitly configured read-only Gmail OAuth credential or compatible Google credential source in the deployment environment.

That activation is **not** performed by this implementation. No credential registration, deployment, mailbox read, production ingestion, production database mutation, scientific publication, taxonomy activation, Knowledge Graph mutation, or spending is authorized by this Brain record.
