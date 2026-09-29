"""Fail-closed exceptions for the Swarm Execution Governor."""

from __future__ import annotations


class GovernorError(Exception):
    """Base class for all Swarm Execution Governor errors."""


class GovernorPolicyError(GovernorError):
    """Raised when a GovernorPolicy is misconfigured."""


class GovernorBlockedError(GovernorError):
    """Raised by begin() when policy evaluation blocks execution."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
