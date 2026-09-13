# OC-EMAIL-GATEWAY-001 — Provider-neutral inbound email boundary

Status: **FOUNDATION IMPLEMENTED / PROVIDER ACTIVATION PENDING**

Issue: #1151

## Purpose

Email becomes a first-class Orchid Continuum input without turning a mailbox into a privileged command channel.

The gateway separates two trust domains:

- **scientific/external intelligence** — research, news, species discoveries, grants, conservation projects, organizations, botanical gardens and technologies;
- **operations** — bug reports, technical support, administrative correspondence and ambiguous messages requiring review.

## Existing Twin foundation

PR #965 already merged the narrowly scoped, read-only Twin Gmail collector. The new email gateway preserves that contract and adds a provider-neutral envelope/routing layer around future transports.

Direct Twin collection remains compatible through the exact historical sender + subject rule. Forwarded Twin material should normally be sent to the `research@` or `intake@` alias so the forwarding sender does not need special trust.

## Logical addresses

The routing contract recognizes these local parts independent of provider:

- `research@orchidcontinuum.org` → governed intelligence assimilation
- `intake@orchidcontinuum.org` → governed intelligence assimilation
- `support@orchidcontinuum.org` → operational ticket
- `help@orchidcontinuum.org` → operational support ticket
- `bugs@orchidcontinuum.org` / `bug@orchidcontinuum.org` → bug ticket
- `admin@orchidcontinuum.org` → administrative ticket

Multiple recognized recipients that span trust domains fail closed to `review`.

## Non-authority contract

Every routing decision defaults to:

- `trusted_instruction = false`
- `canonical_graph_mutation_allowed = false`
- `external_contact_allowed = false`
- `publication_allowed = false`

These are properties of the gateway, not classifications inferred from message text. An email cannot override them by containing instructions.

## Durable storage

Migration `20260823_oc_email_gateway_foundation.sql` creates:

- `oc_email.inbound_messages` — provider/message provenance, normalized envelope, body text, attachment metadata, content digest, routing decision and optional governed intake-source reference;
- `oc_email.tickets` — idempotent operational queue for support, bugs, admin and review mail.

Provider + provider message ID is the primary replay boundary. Internet Message-ID and content SHA-256 are retained as additional deduplication/provenance signals.

Attachment bytes are intentionally outside the normalized envelope. Only metadata may enter until a provider adapter places bytes into the existing immutable/quarantine validation path.

## Research route

`process_inbound_email()` sends research-classified messages through the already merged `ingest_external_intelligence_email()` service. That path may stage intelligence and follow-up verification work, but email ingestion does not itself establish canonical scientific truth.

## Operations route

Support, bug, admin and review messages are written to the transport ledger and receive one idempotent operational ticket. They do not pass through scientific intelligence extraction.

Outbound acknowledgement/reply is not part of this slice.

## Provider adapters

The core gateway intentionally has no dependency on a particular mail host.

Recommended adapter order:

1. Keep the existing Twin Gmail read-only collector for immediate direct Twin value when its credential boundary is configured.
2. Add an adapter matching the production `orchidcontinuum.org` mail host. If Microsoft 365 hosts the mailbox, prefer a Microsoft Graph adapter rather than moving the root-domain MX records.
3. A signed inbound-webhook provider may be used on a dedicated inbound subdomain when useful, without disrupting the primary mailbox provider.

Provider adapters must authenticate transport before calling `process_inbound_email()`; message contents never authenticate themselves.

## Next slice

- establish actual mailbox aliases/shared mailbox;
- implement the selected provider adapter with verified webhook/OAuth transport;
- quarantine and hash attachment bytes before parsing;
- expose protected ticket/intake diagnostics to Mission Control;
- activate existing Twin collection credentials only through deployment secret configuration;
- add outbound acknowledgement/reply only behind a separate authorization policy.
