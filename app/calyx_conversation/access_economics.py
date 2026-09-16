"""Calyx access economics: who may spend a generative (paid) provider turn.

Release-1 journey 3 requires that a Calyx answer arrive under an explicit
budget policy, and WORKSPACE-001 / OC-FINISH-14D require that public use of
Calyx never draws silently on the nonprofit's development budget. Until now the
Speak path chose a provider purely from environment variables: if a key was
present, every authenticated subject received paid generative turns with no
entitlement check, no per-subject metering and no program ceiling.

This module is the gate in front of that choice. It decides, for one turn,
whether the configured generative provider may be used or whether the turn is
composed by the deterministic governed provider instead. The deterministic path
is always available, so denial degrades the answer's prose, never its evidence.

Policy is explicit and fail-closed:

- ``CALYX_GENERATIVE_ENTITLEMENT_MODE``: ``owner_only`` (default), ``metered``
  or ``disabled``. An unrecognised value is treated as ``disabled``.
- ``CALYX_GENERATIVE_MEMBER_DAILY_TURNS``: in ``metered`` mode, generative
  turns a non-privileged subject may use per UTC day. Default 0 (none).
- ``CALYX_GENERATIVE_DAILY_CEILING_TURNS``: program-wide generative turns per
  UTC day across all tiers. Unset means no ceiling, and the response says so.

Tiers are derived from the authentication the request already carries: an API
key or owner session is ``privileged``; any other authenticated subject is a
``member``. No new identity system is introduced.

The ledger reuses the Research Station record store rather than adding a table.
It is a bounded per-process/per-store counter, not a distributed reservation
system; that is stated in every decision (``ledger.mode``). When the ledger is
unavailable, any decision that depends on a count fails closed.

This gate is separate from, and never draws on, the autonomy Budget Governor
that meters coding-lane provider spend. ``public_budget_isolation`` is
therefore a constant ``True`` in every decision.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from runtime.research_station_store import (
    ProjectRecordStore,
    build_record_store,
    persistence_mode,
)

from .provider import CalyxReplyProvider, DeterministicGovernedReplyProvider

LOGGER = logging.getLogger(__name__)

POLICY_VERSION = "calyx-access-economics/v1"

MODE_ENV = "CALYX_GENERATIVE_ENTITLEMENT_MODE"
MEMBER_QUOTA_ENV = "CALYX_GENERATIVE_MEMBER_DAILY_TURNS"
CEILING_ENV = "CALYX_GENERATIVE_DAILY_CEILING_TURNS"

MODES = ("owner_only", "metered", "disabled")
DEFAULT_MODE = "owner_only"

Tier = Literal["privileged", "member"]
ProviderClass = Literal["generative", "deterministic"]

LEDGER_OWNER_KEY = "calyx-access"
LEDGER_KIND = "generative_turns"
PROGRAM_PROJECT = "program"

_PRIVILEGED_AUTH_TYPES = frozenset({"api_key", "owner_session"})


def _utc_day(now: datetime | None = None) -> str:
    return (now or datetime.now(tz=timezone.utc)).strftime("%Y-%m-%d")


def _non_negative_int(raw: str | None) -> int | None:
    """Parse a quota/ceiling; ``None`` when unset or unusable (reported, not guessed)."""
    text = (raw or "").strip()
    if not text:
        return None
    try:
        value = int(text)
    except ValueError:
        return None
    return max(0, value)


def is_generative_provider(provider: CalyxReplyProvider) -> bool:
    return not isinstance(provider, DeterministicGovernedReplyProvider)


def resolve_tier(auth: Mapping[str, Any]) -> Tier:
    return "privileged" if str(auth.get("auth_type") or "") in _PRIVILEGED_AUTH_TYPES else "member"


# Ledger -------------------------------------------------------------------------


class LedgerUnavailable(RuntimeError):
    pass


class GenerativeTurnLedger:
    """Per-subject and program-wide daily counters over the record store."""

    def __init__(self, store: ProjectRecordStore, *, mode: str) -> None:
        self._store = store
        self.mode = mode

    def _record_id(self, day: str) -> str:
        return day

    def count(self, project_id: str, day: str) -> int:
        try:
            record = self._store.get(
                owner_key=LEDGER_OWNER_KEY,
                project_id=project_id,
                kind=LEDGER_KIND,
                record_id=self._record_id(day),
            )
        except Exception as exc:
            raise LedgerUnavailable(str(exc)) from exc
        return int((record or {}).get("count") or 0)

    def _write(self, project_id: str, day: str, count: int) -> None:
        try:
            self._store.put(
                owner_key=LEDGER_OWNER_KEY,
                project_id=project_id,
                kind=LEDGER_KIND,
                record_id=self._record_id(day),
                record={
                    "count": max(0, count),
                    "day": day,
                    "updated_at": datetime.now(tz=timezone.utc).isoformat(),
                },
            )
        except Exception as exc:
            raise LedgerUnavailable(str(exc)) from exc

    def reserve(self, project_id: str, day: str) -> int:
        current = self.count(project_id, day)
        self._write(project_id, day, current + 1)
        return current + 1

    def release(self, project_id: str, day: str) -> int:
        current = self.count(project_id, day)
        self._write(project_id, day, current - 1)
        return max(0, current - 1)


# Decision -----------------------------------------------------------------------


@dataclass(frozen=True)
class AccessDecision:
    policy_version: str
    mode: str
    mode_source: str
    tier: Tier
    subject: str
    day: str
    generative_requested: bool
    generative_provider_configured: bool
    generative_allowed: bool
    decision_reason: str
    provider_class: ProviderClass
    quota: dict[str, Any]
    ceiling: dict[str, Any]
    ledger: dict[str, Any]
    reserved: tuple[str, ...] = field(default_factory=tuple)
    public_budget_isolation: Literal[True] = True
    development_budget_governor_charged: Literal[False] = False

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reserved"] = list(self.reserved)
        return payload


class CalyxAccessPolicy:
    """Decides and meters generative provider use for Speak turns."""

    def __init__(
        self,
        *,
        env: Mapping[str, str] | None = None,
        store: ProjectRecordStore | None = None,
    ) -> None:
        self._env = env
        self._store = store
        self._ledger: GenerativeTurnLedger | None = None

    # -- configuration ------------------------------------------------------

    def _environ(self) -> Mapping[str, str]:
        return self._env if self._env is not None else os.environ

    def mode(self) -> tuple[str, str]:
        """``(mode, source)`` where source explains how the mode was resolved."""
        raw = str(self._environ().get(MODE_ENV, "")).strip().casefold()
        if not raw:
            return DEFAULT_MODE, "default"
        if raw in MODES:
            return raw, "environment"
        return "disabled", f"unrecognised_value_fail_closed:{raw[:40]}"

    def member_daily_turns(self) -> int:
        return _non_negative_int(self._environ().get(MEMBER_QUOTA_ENV)) or 0

    def daily_ceiling(self) -> int | None:
        return _non_negative_int(self._environ().get(CEILING_ENV))

    def ledger(self) -> GenerativeTurnLedger:
        if self._ledger is None:
            store = self._store if self._store is not None else build_record_store(env=self._environ())
            self._ledger = GenerativeTurnLedger(store, mode=persistence_mode(self._environ()))
        return self._ledger

    def describe(self) -> dict[str, Any]:
        mode, source = self.mode()
        return {
            "policy_version": POLICY_VERSION,
            "mode": mode,
            "mode_source": source,
            "modes": list(MODES),
            "tiers": {
                "privileged": "API key or owner session",
                "member": "any other authenticated subject",
            },
            "member_daily_turns": self.member_daily_turns() if mode == "metered" else 0,
            "daily_ceiling_turns": self.daily_ceiling(),
            "ledger_mode": self.ledger().mode,
            "deterministic_path_always_available": True,
            "public_budget_isolation": True,
            "development_budget_governor_charged": False,
            "environment": [MODE_ENV, MEMBER_QUOTA_ENV, CEILING_ENV],
        }

    # -- decisions ------------------------------------------------------------

    def _base(
        self,
        *,
        auth: Mapping[str, Any],
        subject: str,
        generative_mode: str,
        candidate: CalyxReplyProvider,
    ) -> dict[str, Any]:
        mode, source = self.mode()
        return {
            "policy_version": POLICY_VERSION,
            "mode": mode,
            "mode_source": source,
            "tier": resolve_tier(auth),
            "subject": subject,
            "day": _utc_day(),
            "generative_requested": generative_mode != "never",
            "generative_provider_configured": is_generative_provider(candidate),
            "quota": {"member_daily_turns": None, "used_today": None, "remaining_today": None},
            "ceiling": {"daily_turns": self.daily_ceiling(), "used_today": None, "remaining_today": None},
            "ledger": {"mode": self.ledger().mode, "status": "not_consulted"},
        }

    @staticmethod
    def _deny(base: dict[str, Any], reason: str) -> AccessDecision:
        return AccessDecision(
            generative_allowed=False,
            decision_reason=reason,
            provider_class="deterministic",
            **base,
        )

    def decide(
        self,
        *,
        auth: Mapping[str, Any],
        subject: str,
        generative_mode: str,
        candidate: CalyxReplyProvider,
        commit: bool = True,
    ) -> AccessDecision:
        """Decide one turn. With ``commit`` the decision reserves ledger turns.

        Order matters and is deliberate: anything that needs no count is
        decided before the ledger is touched, so a ledger outage only affects
        decisions that genuinely depend on a count.
        """
        base = self._base(auth=auth, subject=subject, generative_mode=generative_mode, candidate=candidate)
        if not base["generative_requested"]:
            return self._deny(base, "generative_not_requested")
        if not base["generative_provider_configured"]:
            return self._deny(base, "no_generative_provider_configured")
        mode = base["mode"]
        if mode == "disabled":
            return self._deny(base, "mode_disabled")
        tier = base["tier"]
        if tier == "member" and mode == "owner_only":
            return self._deny(base, "tier_not_entitled")

        ledger = self.ledger()
        day = base["day"]
        ceiling = self.daily_ceiling()
        member_quota = self.member_daily_turns() if tier == "member" else None
        needs_count = ceiling is not None or tier == "member"

        try:
            program_used = ledger.count(PROGRAM_PROJECT, day) if needs_count else None
            subject_used = ledger.count(f"subject:{subject}", day) if tier == "member" else None
            base["ledger"] = {"mode": ledger.mode, "status": "ok"}
        except LedgerUnavailable as exc:
            base["ledger"] = {"mode": ledger.mode, "status": "unavailable", "error": str(exc)[:200]}
            if needs_count:
                return self._deny(base, "ledger_unavailable")
            program_used = None
            subject_used = None

        if ceiling is not None and program_used is not None:
            base["ceiling"] = {
                "daily_turns": ceiling,
                "used_today": program_used,
                "remaining_today": max(0, ceiling - program_used),
            }
            if program_used >= ceiling:
                return self._deny(base, "program_ceiling_reached")

        if tier == "member":
            quota = member_quota or 0
            used = subject_used or 0
            base["quota"] = {
                "member_daily_turns": quota,
                "used_today": used,
                "remaining_today": max(0, quota - used),
            }
            if used >= quota:
                return self._deny(base, "member_quota_exhausted")

        reserved: list[str] = []
        if commit:
            try:
                if ceiling is not None:
                    ledger.reserve(PROGRAM_PROJECT, day)
                    reserved.append(PROGRAM_PROJECT)
                    base["ceiling"]["used_today"] = base["ceiling"]["used_today"] + 1
                    base["ceiling"]["remaining_today"] = max(0, ceiling - base["ceiling"]["used_today"])
                if tier == "member":
                    ledger.reserve(f"subject:{subject}", day)
                    reserved.append(f"subject:{subject}")
                    base["quota"]["used_today"] = base["quota"]["used_today"] + 1
                    base["quota"]["remaining_today"] = max(0, quota - base["quota"]["used_today"])
                elif ceiling is None:
                    # Privileged, unmetered: count for observability only; a
                    # failure here must not deny the turn or hide the failure.
                    try:
                        ledger.reserve(PROGRAM_PROJECT, day)
                        reserved.append(PROGRAM_PROJECT)
                    except LedgerUnavailable as exc:
                        base["ledger"] = {"mode": ledger.mode, "status": "unavailable", "error": str(exc)[:200]}
            except LedgerUnavailable as exc:
                base["ledger"] = {"mode": ledger.mode, "status": "unavailable", "error": str(exc)[:200]}
                self._release(reserved, day)
                return self._deny(base, "ledger_unavailable")

        return AccessDecision(
            generative_allowed=True,
            decision_reason="allowed_privileged" if tier == "privileged" else "allowed_metered",
            provider_class="generative",
            reserved=tuple(reserved),
            **base,
        )

    def preview(
        self, *, auth: Mapping[str, Any], subject: str, candidate: CalyxReplyProvider
    ) -> AccessDecision:
        """What :meth:`decide` would return for a generative turn, without reserving."""
        return self.decide(auth=auth, subject=subject, generative_mode="auto", candidate=candidate, commit=False)

    def release(self, decision: AccessDecision) -> None:
        """Return reserved turns after the provider failed to produce a reply."""
        self._release(list(decision.reserved), decision.day)

    def _release(self, reserved: list[str], day: str) -> None:
        for project_id in reserved:
            try:
                self.ledger().release(project_id, day)
            except LedgerUnavailable as exc:
                LOGGER.warning("calyx access ledger release failed project=%s day=%s error=%s", project_id, day, exc)


#: Process-wide policy used by the Speak routes; tests substitute their own.
ACCESS_POLICY = CalyxAccessPolicy()
