from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

Audience = Literal["grower", "student", "researcher", "conservation", "general"]
ExpertiseLevel = Literal["beginner", "intermediate", "advanced", "expert"]
Verbosity = Literal["concise", "standard", "detailed"]
TechnicalDepth = Literal["low", "medium", "high"]
Conversationality = Literal["low", "medium", "high"]


class VoiceProfile(BaseModel):
    """Presentation-only preferences for a validated Calyx answer."""

    audience: Audience = "general"
    expertise_level: ExpertiseLevel = "intermediate"
    verbosity: Verbosity = "standard"
    technical_depth: TechnicalDepth = "medium"
    teaching_mode: bool = False
    conversationality: Conversationality = "medium"


@dataclass(frozen=True, slots=True)
class AdaptiveRenderResult:
    answer: str
    mode: str
    firewall_passed: bool
    fallback_used: bool
    profile: VoiceProfile


class ScientificFirewallError(ValueError):
    """Raised when a presentation rewrite changes protected scientific content."""


def protected_segments_from_answer(answer: str) -> tuple[str, ...]:
    """Extract exact scientific/provenance-bearing lines from a canonical answer.

    The adaptive renderer may change framing and headings only. Protected lines
    carry counts, pathway explanations/confidence, evidence identity/state, or
    the epistemic interpretation boundary and therefore must survive exactly.
    """

    protected: list[str] = []
    for line in answer.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("Reasoning map:"):
            protected.append(line)
        elif stripped.startswith("Indexed evidence:"):
            protected.append(line)
        elif stripped.startswith("No qualifying causal pathway"):
            protected.append(line)
        elif stripped.startswith("No eligible indexed evidence"):
            protected.append(line)
        elif stripped.startswith("Interpretation boundary:"):
            protected.append(line)
        elif stripped[:1].isdigit() and ". " in stripped:
            protected.append(line)
    return tuple(protected)


def verify_scientific_firewall(
    canonical_answer: str,
    candidate_answer: str,
    protected_segments: tuple[str, ...] | None = None,
) -> None:
    """Reject a candidate if any protected canonical segment changed or vanished."""

    segments = protected_segments or protected_segments_from_answer(canonical_answer)
    for segment in segments:
        if segment not in candidate_answer:
            raise ScientificFirewallError(
                "adaptive communication changed protected scientific content"
            )


def _audience_intro(profile: VoiceProfile) -> str:
    if profile.audience == "grower":
        return "Here is the practical interpretation Calyx can support from the current Orchid Continuum evidence."
    if profile.audience == "student":
        return "Here is the evidence-backed reasoning path, with the scientific limits kept explicit."
    if profile.audience == "researcher":
        return "Calyx assembled the current inspectable causal pathways and indexed evidence for review."
    if profile.audience == "conservation":
        return "Here is the current evidence-backed interpretation, preserving uncertainty and provenance for conservation use."
    return "Here is Calyx's evidence-backed interpretation from the current Orchid Continuum record."


def _path_heading(profile: VoiceProfile) -> str:
    if profile.audience == "grower":
        return "What the current pathways suggest:"
    if profile.audience == "student" or profile.teaching_mode:
        return "How the reasoning connects:"
    if profile.audience == "researcher":
        return "Highest-priority inspectable pathways:"
    return "Evidence-linked pathways:"


def _evidence_heading(profile: VoiceProfile) -> str:
    if profile.audience == "grower":
        return "Evidence Calyx checked:"
    if profile.audience == "student" or profile.teaching_mode:
        return "Evidence behind the explanation:"
    if profile.audience == "researcher":
        return "Indexed evidence:"
    return "Supporting indexed evidence:"


def deterministic_render(canonical_answer: str, profile: VoiceProfile) -> str:
    """Apply presentation-only replacements without invoking any model provider."""

    answer = canonical_answer.replace(
        "Calyx built a read-only causal reasoning map from Orchid Continuum graph state and searched indexed evidence before answering.",
        _audience_intro(profile),
        1,
    )
    answer = answer.replace(
        "Highest-priority inspectable pathways:",
        _path_heading(profile),
        1,
    )

    # The canonical "Indexed evidence: N ..." line is protected. Only replace
    # the heading in answers where a separate heading exists in the future.
    if "Supporting indexed evidence:\n" in answer:
        answer = answer.replace(
            "Supporting indexed evidence:", _evidence_heading(profile), 1
        )

    if profile.teaching_mode:
        answer = answer.replace(
            "Question: ",
            "Question to keep in view: ",
            1,
        )

    return answer


def render_adaptive_answer(
    canonical_answer: str,
    profile: VoiceProfile,
) -> AdaptiveRenderResult:
    """Render a user-tailored answer and fail closed to canonical scientific text."""

    protected_segments = protected_segments_from_answer(canonical_answer)
    candidate = deterministic_render(canonical_answer, profile)
    try:
        verify_scientific_firewall(
            canonical_answer,
            candidate,
            protected_segments=protected_segments,
        )
    except ScientificFirewallError:
        return AdaptiveRenderResult(
            answer=canonical_answer,
            mode="deterministic",
            firewall_passed=False,
            fallback_used=True,
            profile=profile,
        )

    return AdaptiveRenderResult(
        answer=candidate,
        mode="deterministic",
        firewall_passed=True,
        fallback_used=False,
        profile=profile,
    )
