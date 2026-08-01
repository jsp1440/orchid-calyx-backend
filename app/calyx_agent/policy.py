from __future__ import annotations

import re

from .models import ActionClass, RequestIntent


_MUTATION_WORDS = {
    "merge", "deploy", "delete", "migrate", "restart", "schedule", "publish",
    "activate", "disable", "enable", "commit", "push", "write", "change production",
}
_SCIENTIFIC_PUBLICATION_WORDS = {
    "publish scientific", "approve scientific", "canonical knowledge",
    "promote evidence", "publish conclusion",
}
_AUDIT_WORDS = {"audit", "diagnose", "inspect", "review", "assess", "status"}
_BUILD_WORDS = {"build", "implement", "fix", "improve", "create branch", "pull request", "pr"}
_MONITOR_WORDS = {"monitor", "watch", "alert", "track", "check regularly"}


def normalize_request(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().casefold())


def classify_intent(text: str) -> RequestIntent:
    normalized = normalize_request(text)
    if any(term in normalized for term in _SCIENTIFIC_PUBLICATION_WORDS):
        return RequestIntent.SCIENTIFIC_PUBLICATION
    if any(term in normalized for term in _MUTATION_WORDS):
        return RequestIntent.MUTATE
    if any(term in normalized for term in _BUILD_WORDS):
        return RequestIntent.PLAN_BUILD
    if any(term in normalized for term in _MONITOR_WORDS):
        return RequestIntent.MONITOR
    if "audit" in normalized:
        return RequestIntent.AUDIT
    if any(term in normalized for term in _AUDIT_WORDS):
        return RequestIntent.INSPECT
    return RequestIntent.GENERAL


def required_action_class(intent: RequestIntent) -> ActionClass:
    if intent is RequestIntent.SCIENTIFIC_PUBLICATION:
        return ActionClass.SCIENTIFIC_APPROVAL
    if intent is RequestIntent.MUTATE:
        return ActionClass.OWNER_APPROVAL
    if intent in {RequestIntent.PLAN_BUILD, RequestIntent.MONITOR}:
        return ActionClass.PREPARE_ONLY
    return ActionClass.READ_ONLY


def approval_reason(intent: RequestIntent) -> str | None:
    action_class = required_action_class(intent)
    if action_class is ActionClass.SCIENTIFIC_APPROVAL:
        return "Canonical scientific approval must pass the existing review and publication gates."
    if action_class is ActionClass.OWNER_APPROVAL:
        return "The request includes a consequential mutation and requires explicit owner approval."
    return None
