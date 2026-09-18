"""What a task needs, and whether any deterministic executor can supply it.

This is the registry that replaces "does the body contain a hard word" with
"which capabilities does this task require, and does the repository already have
a deterministic executor for them".

Adding a capability here is a deliberate act. An unrecognised capability is
**not** silently treated as provider-requiring — that is how a deterministic task
ends up spending money — and it is not silently treated as deterministic either,
which is how a task would be handed to a worker that cannot do it. It raises.
"""

from __future__ import annotations

from dataclasses import dataclass


class CapabilityUnknown(ValueError):
    """A task declared a capability nobody has classified.

    Raised rather than guessed. Guessing toward the provider spends money on a
    task that may not need it; guessing toward deterministic hands work to an
    executor that cannot complete it and reports a false success.
    """


@dataclass(frozen=True)
class Capability:
    """One thing a task needs done, and what can do it.

    ``provider_required`` is a statement about the *capability*, not about the
    task's difficulty. Reconciling a 147,000-row crosswalk is laborious and
    entirely deterministic; paraphrasing one sentence into plain English for a
    learner is trivial and needs a language model. Effort and provider
    requirement are independent.
    """

    name: str
    provider_required: bool
    summary: str
    deterministic_alternative: str = ""

    def __post_init__(self) -> None:
        if self.provider_required and not self.deterministic_alternative:
            raise ValueError(
                f"capability {self.name!r} claims a provider is required but names no "
                "deterministic alternative; state what was considered and why it is "
                "insufficient, so the claim can be re-examined when local evidence grows"
            )


def _cap(name: str, summary: str) -> Capability:
    return Capability(name=name, provider_required=False, summary=summary)


def _provider_cap(name: str, summary: str, alternative: str) -> Capability:
    return Capability(
        name=name,
        provider_required=True,
        summary=summary,
        deterministic_alternative=alternative,
    )


#: Deterministic capabilities. Every one of these is executed by code already in
#: this repository; none calls a paid provider. They are listed explicitly so
#: that "this task is deterministic" is a checkable claim rather than an opinion.
_DETERMINISTIC = (
    _cap("taxonomy-resolution", "Resolve a name against the canonical taxonomy tables."),
    _cap("literature-evidence-lookup", "Retrieve stored literature records and their provenance."),
    _cap("interaction-kg-lookup", "Retrieve stored interaction and knowledge-graph edges."),
    _cap("geospatial-context", "Assemble bounded environmental and geographic context."),
    _cap("reasoning-map-assembly", "Assemble an inspectable reasoning map from retrieved evidence."),
    _cap("contradiction-detection", "Compare retrieved claims and mark those that conflict."),
    _cap("evidence-gap-detection", "Mark what the retrieved evidence does not cover."),
    _cap("provenance-assembly", "Attach source and provenance to every retrieved claim."),
    _cap("schema-validation", "Validate an artifact against its declared schema."),
    _cap("fixture-execution", "Run a stored deterministic fixture and compare it to expectations."),
    _cap("reconcile", "Reconcile queue, lease and label state against durable receipts."),
    _cap("test-execution", "Run the repository's own test suites."),
    _cap("lint-execution", "Run the repository's own linters and formatters."),
    _cap("locality-redaction", "Withhold or generalise protected locality before anything leaves."),
)

#: Capabilities that genuinely need a language model. Each must name what was
#: considered deterministically and why it is insufficient — that text becomes
#: part of the preserved intent record, so a denied request can be re-examined
#: rather than merely repeated.
_PROVIDER = (
    _provider_cap(
        "natural-language-explanation",
        "Render an assembled reasoning map into prose a non-specialist can follow.",
        "The reasoning map, its evidence states and its gaps are already assembled "
        "deterministically and can be presented as structured fields; only the "
        "connecting prose needs generation.",
    ),
    _provider_cap(
        "free-text-intent-parsing",
        "Interpret an arbitrary typed or spoken question into a structured intent.",
        "A stored fixture covers the known question forms deterministically; only "
        "an unseen free-text phrasing needs generation.",
    ),
    _provider_cap(
        "open-ended-code-authoring",
        "Author a non-trivial implementation from a prose specification.",
        "Templated and fixture-driven generation covers the repetitive cases; only "
        "genuinely novel implementation needs a model.",
    ),
    _provider_cap(
        "literature-summarisation",
        "Summarise a paper whose text is stored but whose summary is not.",
        "Stored abstracts and extracted fields are served directly where present; "
        "only a paper with neither needs generation.",
    ),
)

CAPABILITIES: dict[str, Capability] = {c.name: c for c in (*_DETERMINISTIC, *_PROVIDER)}


def is_provider_capability(name: str) -> bool:
    """True when this capability genuinely requires an external provider.

    Raises :class:`CapabilityUnknown` for a name nobody has classified.
    """
    try:
        return CAPABILITIES[name].provider_required
    except KeyError as exc:
        raise CapabilityUnknown(
            f"capability {name!r} is not classified; add it to the registry as "
            "deterministic or provider-requiring rather than letting routing guess"
        ) from exc


def classify_capabilities(names: list[str]) -> tuple[list[str], list[str]]:
    """Split declared capabilities into deterministic and provider-requiring.

    Returns ``(deterministic, provider_required)``, each sorted and deduplicated.
    A task with entries in both lists is a task whose deterministic part must run
    now and whose provider part parks — never a task that blocks as a whole.
    """
    deterministic: set[str] = set()
    provider: set[str] = set()
    for name in names:
        if is_provider_capability(name):
            provider.add(name)
        else:
            deterministic.add(name)
    return sorted(deterministic), sorted(provider)
