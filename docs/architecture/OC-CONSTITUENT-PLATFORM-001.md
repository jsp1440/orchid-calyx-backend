# OC-CONSTITUENT-PLATFORM-001 — Constituent, Entitlement & Communications Foundation

Status: foundation only. No outbound provider, production send, payment capture, campaign execution, or Society website is enabled by this slice.

## Purpose

Orchid Continuum needs one reusable relationship layer for accounts, members, donors, learners, partners, report recipients, support users, and future participating societies. This foundation prevents individual modules from inventing incompatible user/email/membership models while preserving existing authentication and scientific privacy boundaries.

## Boundaries

- Authentication remains external. `identity_links.auth_subject` stores only a stable subject such as `supabase:<uuid>`; it is not an auth or password table.
- Organization-scoped memberships, preferences, suppressions, and communication intents carry an explicit organization boundary. Future Society CRM authorization must enforce this scope at the service/database session boundary before tenant UI is mounted.
- Society membership never grants access to private Conservatory, OASIS, Calyx, research, donor, or other personal data. Any future sharing requires an explicit separate grant.
- Inbound email and other untrusted content cannot authorize outbound contact.
- No payment credential, card number, bank credential, provider secret, or payment settlement data belongs in these schemas.
- No outbound provider is connected in this slice.

## Slice 1 — constituent and membership foundation

`oc_constituent` adds organizations, constituents, external identity links, scoped email addresses, and organization memberships. A constituent can exist before a web account and can later be linked to a verified external auth subject. That allows imported society records without pretending every contact is already an authenticated OC user.

Membership is a relationship with an organization, not a synonym for login identity. Free/paid/sponsored entitlements can therefore be layered later without coupling authentication to billing.

## Slice 2 — preference and suppression ledger

Communication preferences are purpose-specific and append-oriented so consent provenance is retained. Supported purposes are transactional, membership relationship, research delivery, community, fundraising, marketing, support, and administrative.

Suppressions are evaluated before preferences. Hard bounce, complaint, invalid-address, unsubscribe, and administrative blocks therefore fail closed before campaign segmentation. Required-service purposes are deliberately narrow and do not convert society membership into marketing consent.

## Slice 3 — communication intent and frozen audience

Outbound work begins as a communication intent. An intent records purpose, initiating module/principal, content or artifact references, audience definition, required authorization class, and state.

The audience is materialized into an audience snapshot. Each recipient carries an allow/suppress decision and reason. The exact decision set is hashed before the snapshot is frozen. Database triggers prevent recipient mutation or snapshot re-freezing after that point. Approval events bind the approving principal and authorization class to the exact audience hash.

The application state machine is fail closed:

`draft -> awaiting_approval -> approved -> sending -> completed|partially_failed`

Cancellation is allowed only from bounded pre-terminal states. An intent cannot enter the approval boundary until its audience is frozen, and it cannot become approved without a recorded approval event.

Marketing, fundraising, and community purposes require approval even for one recipient. Any multi-recipient intent is conservatively treated as approval-required. A future narrowly authorized one-to-one “Email me this report” path can therefore be added without weakening campaign controls.

## Future Society CRM extension

The Society product is a consumer of this platform, not the owner of it. The first Society slice may add tenant authorization/RLS session contracts, membership levels and renewals, event registration, member portal, external payment-provider event adapters, HTML/newsletter composition, and a generated public Society Page/Join link.

Those features must remain outside the scientific critical path and must not grant a society access to a member's private Orchid Continuum scientific or collection data.

## Explicitly deferred

- live BetterWorld, Pledge It, Stripe, PayPal, Microsoft, SES, Postmark, Resend, or other provider credentials
- payment processing or settlement
- delivery adapters/webhooks
- campaign sending
- public signup or member portal UI
- Society websites/widgets
- donor financial-system-of-record behavior
- production schema application/deployment
