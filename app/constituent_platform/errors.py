"""Administrator-facing explanations for society CRM error codes.

Every message says what happened and what an administrator can do next, without
exposing secrets, SQL, stack traces, or another tenant's data.
"""

from __future__ import annotations

_MESSAGES: dict[str, str] = {
    "ORGANIZATION_NOT_FOUND": "No society with this address exists. Check the society link.",
    "ORGANIZATION_SLUG_TAKEN": "That society address is already in use. Choose a different short name.",
    "INVALID_ORGANIZATION_SLUG": "Society short names use 2-63 lowercase letters, digits and hyphens.",
    "MEMBERSHIP_NOT_FOUND": "That membership does not exist in this society.",
    "CONSTITUENT_NOT_FOUND": "That person does not exist in this society.",
    "MEMBERSHIP_LEVEL_NOT_FOUND": "That membership level does not exist in this society.",
    "STAFF_ROLE_NOT_FOUND": "That person does not currently hold this role.",
    "IDENTITY_BINDING_NOT_FOUND": "That login is not linked to anyone in this society.",
    "UNKNOWN_MEMBERSHIP_LEVEL": "That membership level is not configured or is inactive. Create or re-activate it under Membership levels first.",
    "MEMBERSHIP_LEVEL_EXISTS": "A membership level with this code already exists. Edit the existing level instead.",
    "INVALID_MEMBERSHIP_LEVEL_CODE": "Level codes use 1-40 lowercase letters, digits, hyphens or underscores.",
    "INVALID_DUES_AMOUNT": "Dues must be a whole number of cents, zero or more.",
    "INVALID_CURRENCY": "Currency must be a three-letter ISO code such as USD.",
    "INVALID_MEMBERSHIP_TERM": "Membership terms are between 1 and 1200 months.",
    "INVALID_GRACE_DAYS": "Grace periods are between 0 and 366 days.",
    "INVALID_HOUSEHOLD_SIZE": "Household size is between 1 and 20 people.",
    "DUPLICATE_MEMBER_EMAIL": "Someone in this society already uses this email. Open the existing member instead, or confirm this is a different person.",
    "MEMBERSHIP_ALREADY_EXISTS": "This person already has a membership in this society. Renew or change the existing membership.",
    "MEMBERSHIP_RENEWAL_REQUIRED": "This membership has no paid-through date in the future. Record a renewal or payment instead of setting it active.",
    "MEMBERSHIP_TRANSITION_REASON_REQUIRED": "Cancelling or reinstating a membership needs a short reason for the audit history.",
    "MEMBERSHIP_CANNOT_START_CANCELLED": "A new membership cannot start as cancelled.",
    "MEMBERSHIP_EXPIRY_REQUIRED": "An active membership needs an expiry date.",
    "RENEWAL_KEY_REQUIRED": "A renewal reference is required so the renewal is applied only once.",
    "RENEWAL_KEY_CONFLICT": "This renewal reference was already used for a different member. Use a new reference.",
    "HOUSEHOLD_CAPACITY_EXCEEDED": "This membership level does not allow that many household members. Change to a household/family level first.",
    "HOUSEHOLD_MEMBER_IS_PRIMARY": "The primary member is already covered by this membership.",
    "PERSON_ALREADY_IN_HOUSEHOLD": "That person is already part of a household membership.",
    "LAST_ADMIN_REQUIRED": "A society must keep at least one administrator. Grant the admin role to someone else first.",
    "AUTH_SUBJECT_ALREADY_BOUND": "That login is already linked to a different person in this society. Unlink it first if this is intentional.",
    "CONSTITUENT_ALREADY_BOUND": "That person is already linked to a different login. Unlink it first if this is intentional.",
    "INVALID_EMAIL": "That email address is not valid.",
    "INVALID_PHONE": "Phone numbers need 7-15 digits, optionally starting with +.",
    "INVALID_COUNTRY_CODE": "Country must be a two-letter code such as US.",
    "ADDRESS_LINE1_REQUIRED": "The first address line is required.",
    "MEMBER_NAME_REQUIRED": "A member name is required.",
    "EXTERNAL_LINK_CONFLICT": "This imported record is already linked to a different person. Resolve the conflict in the import report.",
    "INVITE_INVALID_OR_EXPIRED": "This link code is not valid. It may have expired or already been used; ask the society for a new one.",
    "PORTAL_NOT_LINKED": "Your login is not linked to a membership in this society yet. Use the link code the society sent you.",
    "PORTAL_REQUIRES_MEMBER_LOGIN": "Sign in with your own member account to use the member portal.",
    "INVALID_INVITE_TTL": "Link codes can be valid for 1 to 90 days.",
    "PLATFORM_OPERATOR_REQUIRED": "Only the Orchid Continuum platform operator can do this.",
    "SOCIETY_CRM_DISABLED": "The society CRM is not enabled on this server yet.",
    "CRM_DATABASE_UNAVAILABLE": "The CRM database could not be reached, so nothing was changed. Try again in a few minutes; if it continues, check the system status page.",
    "CRM_SCHEMA_NOT_READY": "The CRM database is missing required tables. An operator must apply the CRM migrations before this feature can be used.",
}

_CAPABILITY_HINTS: dict[str, str] = {
    "roster.read": "view the member roster",
    "member.write": "edit member details",
    "membership.write": "change memberships",
    "payment.read": "view payments",
    "payment.write": "record payments",
    "donation.read": "view donations",
    "donation.write": "record donations",
    "member.import": "import members",
    "roster.export": "export the roster",
    "organization.export": "export all society data",
    "audit.read": "view the audit history",
    "role.admin": "manage roles and logins",
    "settings.write": "change society settings",
    "diagnostics.read": "view diagnostics",
}


def message_for(code: str) -> str:
    if code.startswith("SOCIETY_CAPABILITY_REQUIRED:"):
        capability = code.split(":", 1)[1]
        action = _CAPABILITY_HINTS.get(capability, capability)
        return f"Your account does not have permission to {action} in this society. Ask a society administrator to grant a suitable role."
    if code.startswith("INVALID_MEMBERSHIP_TRANSITION:"):
        change = code.split(":", 1)[1].replace("->", " to ")
        return f"A membership cannot move directly from {change}."
    if code.startswith("FORBIDDEN_SOCIETY_ENTITLEMENT:"):
        return "Society membership levels may only grant society benefits (codes starting with 'society.')."
    if code.startswith("MEMBERSHIP_LEVEL_FIELD_NOT_EDITABLE:") or code.startswith("MEMBER_FIELD_NOT_EDITABLE:"):
        return f"The field '{code.split(':', 1)[1]}' cannot be changed here."
    return _MESSAGES.get(code, "The request could not be completed. No changes were made.")


def error_body(code: str) -> dict[str, str]:
    return {"code": code, "message": message_for(code)}


CONFLICT_CODES = frozenset(
    {
        "ORGANIZATION_SLUG_TAKEN", "MEMBERSHIP_LEVEL_EXISTS", "DUPLICATE_MEMBER_EMAIL",
        "MEMBERSHIP_ALREADY_EXISTS", "RENEWAL_KEY_CONFLICT", "LAST_ADMIN_REQUIRED",
        "AUTH_SUBJECT_ALREADY_BOUND", "CONSTITUENT_ALREADY_BOUND", "PERSON_ALREADY_IN_HOUSEHOLD",
        "EXTERNAL_LINK_CONFLICT", "HOUSEHOLD_CAPACITY_EXCEEDED",
    }
)
