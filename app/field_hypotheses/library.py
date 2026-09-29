"""Deterministic hypothesis rule library for the field hypothesis loop.

This is not an inference engine and it calls no provider. It is a curated,
versioned library of *explanation classes* for an orchid–visitor interaction,
drawn from the pollination strategy and evidence vocabularies in Orchid
Continuum Brain KO-0038. Given the observer-level cues in an observation
snapshot, it selects the classes that could explain what was seen, phrases each
as a testable hypothesis with what would support and what would contradict it,
and assembles the non-destructive field follow-ups that discriminate between
them.

Two alternatives are structurally guaranteed to compete whenever they apply:
the visitor is not an effective pollinator, and the subject is misidentified.
Without them a "deception" label would be the only explanation on the table,
which is exactly the premature promotion this loop exists to prevent.

Ordering is by cue-match count, then by library order. There are no
probabilities: a match count says how many cues a class is consistent with,
not how likely it is.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .schemas import (
    FloralSignalCue,
    FollowUpObservation,
    HypothesisClass,
    ObservationSnapshot,
    ObserverCertainty,
    ReproductiveOutcomeCue,
    RewardCheck,
    VisitorBehavior,
    VisitorGroup,
)

LIBRARY_VERSION = "field-hypothesis-library/2026.09-v1"
LIBRARY_BASIS = (
    "Orchid Continuum Brain KO-0038 pollination strategy and evidence vocabularies; "
    "KO-0024 review status vocabulary. Deterministic cue matching, no provider call."
)

#: Question families seeded by the Deception Lab (frontend DECEPTION-LAB-001).
QUESTION_FAMILIES: tuple[str, ...] = (
    "repeated-evolution",
    "signal-chemistry",
    "pollinator-specificity",
    "visual-chemical-tactile",
    "reproductive-success",
    "reward-deception-transitions",
)

#: Every follow-up protocol carries these. They are constraints on the
#: researcher, not on the hypotheses.
PROTOCOL_CONSTRAINTS: tuple[str, ...] = (
    "Do not collect, capture, mark or handle plants, flowers or visitors; observe and record only.",
    "Do not dissect flowers or probe nectaries; reward checks are visual.",
    (
        "Record exact locality only in the Field Journal under its locality sensitivity class; "
        "never in hypothesis notes, evidence summaries or media captions."
    ),
    "Photograph or film rather than tag; a physical marker can reveal a plant's position.",
    (
        "These suggestions are machine-assisted and provider-free. They are not scientific "
        "determinations and nothing here is promoted to canonical knowledge."
    ),
)

# Cue tokens -----------------------------------------------------------------


def cue_tokens(snapshot: ObservationSnapshot) -> list[str]:
    """Flatten a snapshot into the sorted cue tokens the templates match on."""
    interaction = snapshot.interaction
    tokens: set[str] = set()
    if interaction.visitor_observed:
        tokens.add("visitor:observed")
        # Visitor identity and behaviour only mean something when there was one.
        tokens.add(f"group:{interaction.visitor_group.value}")
        for behavior in interaction.visitor_behaviors:
            tokens.add(f"behavior:{behavior.value}")
    else:
        tokens.add("visitor:absent")
    tokens.add(f"reward:{interaction.reward_check.value}")
    for cue in interaction.floral_signal_cues:
        tokens.add(f"signal:{cue.value}")
    tokens.add(f"outcome:{interaction.reproductive_outcome.value}")
    tokens.add(f"certainty:{snapshot.epistemic_certainty.value.lower()}")
    return sorted(tokens)


# Templates -------------------------------------------------------------------


@dataclass(frozen=True)
class FollowUp:
    step_id: str
    instruction: str
    purpose: str
    while_on_site: bool
    discriminates: tuple[HypothesisClass, ...]

    def to_schema(self) -> FollowUpObservation:
        return FollowUpObservation(
            step_id=self.step_id,
            instruction=self.instruction,
            purpose=self.purpose,
            while_on_site=self.while_on_site,
            discriminates=list(self.discriminates),
        )


@dataclass(frozen=True)
class HypothesisTemplate:
    template_id: str
    hypothesis_class: HypothesisClass
    ko_0038_strategy: str
    statement: str
    predictions: tuple[str, ...]
    would_support: tuple[str, ...]
    would_contradict: tuple[str, ...]
    positive_cues: frozenset[str]
    question_family_ids: tuple[str, ...]
    follow_ups: tuple[FollowUp, ...]
    #: Human-readable conditions under which the template is included even
    #: with no cue match. Evaluated by :func:`_always_included`.
    always_included_when: tuple[str, ...] = field(default_factory=tuple)

    def render_statement(self, snapshot: ObservationSnapshot) -> str:
        subject = (snapshot.taxon_hint or "").strip() or "the observed orchid"
        visitor = snapshot.interaction.visitor_group.value.replace("_", " ")
        if visitor in {"unknown", "other"}:
            visitor = "visitor"
        return self.statement.format(subject=subject, visitor=visitor)


def _b(value: VisitorBehavior) -> str:
    return f"behavior:{value.value}"


def _g(value: VisitorGroup) -> str:
    return f"group:{value.value}"


def _s(value: FloralSignalCue) -> str:
    return f"signal:{value.value}"


def _r(value: RewardCheck) -> str:
    return f"reward:{value.value}"


def _o(value: ReproductiveOutcomeCue) -> str:
    return f"outcome:{value.value}"


# Shared follow-ups (same step_id → de-duplicated in the protocol).
_FU_COLUMN_CONTACT = FollowUp(
    step_id="record-column-contact",
    instruction=(
        "Film or photograph each visit and note which visitor body part, if any, touches the "
        "column and where on the labellum the visitor positions itself."
    ),
    purpose="Separates an effective pollinator from an incidental visitor and locates the contact site.",
    while_on_site=True,
    discriminates=(
        HypothesisClass.SEXUAL_DECEPTION,
        HypothesisClass.REWARD_BASED,
        HypothesisClass.NON_POLLINATING_VISIT,
    ),
)
_FU_VISIT_DURATION = FollowUp(
    step_id="time-visits",
    instruction="Time each visit from landing to departure and count visits per 15-minute interval.",
    purpose="Feeding bouts, probe-and-leave visits and prolonged residence have different durations.",
    while_on_site=True,
    discriminates=(
        HypothesisClass.REWARD_BASED,
        HypothesisClass.FOOD_DECEPTION,
        HypothesisClass.SHELTER_MIMICRY,
    ),
)
_FU_POLLINARIA_CHECK = FollowUp(
    step_id="photograph-pollinaria-state",
    instruction=(
        "Photograph the column of visited flowers after each visit and any departing visitor's "
        "head and thorax; note whether pollinia are still present or a pollinarium is carried."
    ),
    purpose="Pollinarium removal or deposition is the direct evidence a visit was a pollination event.",
    while_on_site=True,
    discriminates=(HypothesisClass.NON_POLLINATING_VISIT, HypothesisClass.AUTOGAMY),
)
_FU_VISUAL_REWARD = FollowUp(
    step_id="visual-reward-check",
    instruction=(
        "Without touching the flower, look into the spur or nectary area against the light for "
        "liquid, and photograph it; note glossy or oily surfaces on the labellum."
    ),
    purpose="Presence of a visible reward argues against pure deception.",
    while_on_site=True,
    discriminates=(
        HypothesisClass.REWARD_BASED,
        HypothesisClass.FOOD_DECEPTION,
        HypothesisClass.SEXUAL_DECEPTION,
    ),
)
_FU_SCENT_INTERVALS = FollowUp(
    step_id="note-scent-intervals",
    instruction=(
        "At intervals through the observation window, note whether a scent is detectable, its "
        "character in plain words, and the time; do not sample."
    ),
    purpose="Scent timing and character are cues to the signal channel and target the flower uses.",
    while_on_site=True,
    discriminates=(
        HypothesisClass.SEXUAL_DECEPTION,
        HypothesisClass.BROOD_SITE_DECEPTION,
        HypothesisClass.UNOBSERVED_POLLINATOR,
    ),
)
_FU_COFLOWERING = FollowUp(
    step_id="survey-coflowering-models",
    instruction=(
        "Photograph other flowering plants within about ten metres that share display colour or "
        "shape, and note whether the same visitor groups move between them and the orchid."
    ),
    purpose="A rewarding model visited by the same visitors is what food deception predicts.",
    while_on_site=True,
    discriminates=(HypothesisClass.FOOD_DECEPTION, HypothesisClass.REWARD_BASED),
)
_FU_VISITOR_SEX_ID = FollowUp(
    step_id="photograph-visitor-diagnostics",
    instruction=(
        "Photograph visitors dorsally and laterally at rest so sex and identity can be reviewed "
        "later; do not capture."
    ),
    purpose="Male-only visitation by one species is a prediction of sexual deception.",
    while_on_site=True,
    discriminates=(HypothesisClass.SEXUAL_DECEPTION, HypothesisClass.IDENTIFICATION_UNCERTAINTY),
)
_FU_OVIPOSITION = FollowUp(
    step_id="inspect-labellum-for-eggs",
    instruction="Photograph the labellum surface closely for eggs or larvae without touching it.",
    purpose="Eggs on the flower are direct evidence of brood-site deception.",
    while_on_site=True,
    discriminates=(HypothesisClass.BROOD_SITE_DECEPTION,),
)
_FU_RESIDENCE_WEATHER = FollowUp(
    step_id="record-residence-and-weather",
    instruction=(
        "Record how long visitors remain inside the flower together with temperature, wind and "
        "precipitation at the time."
    ),
    purpose="Long residence in cool or wet conditions is what shelter use predicts.",
    while_on_site=True,
    discriminates=(HypothesisClass.SHELTER_MIMICRY, HypothesisClass.REWARD_BASED),
)
_FU_OTHER_TIMES = FollowUp(
    step_id="observe-other-times",
    instruction=(
        "Return to observe at a different time of day, especially dusk, night and dawn, and "
        "repeat the scent and visitor notes."
    ),
    purpose="A pollinator absent in this window may be active in another.",
    while_on_site=False,
    discriminates=(HypothesisClass.UNOBSERVED_POLLINATOR, HypothesisClass.AUTOGAMY),
)
_FU_AGING_COLUMN = FollowUp(
    step_id="photograph-aging-flowers",
    instruction=(
        "Photograph the column of older, unvisited-looking flowers to see whether pollinia have "
        "moved toward or onto the stigma on their own."
    ),
    purpose="Self-pollination shows in unvisited flowers; visitor pollination does not.",
    while_on_site=True,
    discriminates=(HypothesisClass.AUTOGAMY, HypothesisClass.UNOBSERVED_POLLINATOR),
)
_FU_TAXON_DIAGNOSTICS = FollowUp(
    step_id="photograph-taxon-diagnostics",
    instruction=(
        "Photograph the flower front-on, in profile and from above with a scale reference, "
        "including column and labellum detail, and attach the images to the Field Journal record."
    ),
    purpose="Identification is reviewed from diagnostic images; a Calyx suggestion stays unverified.",
    while_on_site=True,
    discriminates=(HypothesisClass.IDENTIFICATION_UNCERTAINTY,),
)
_FU_FRUIT_SET_REVISIT = FollowUp(
    step_id="revisit-for-fruit-set",
    instruction=(
        "Revisit after flowering and photograph the same inflorescences to record which flowers "
        "set fruit, using the earlier photographs rather than tags to relocate them."
    ),
    purpose="Fruit set is the reproductive outcome every pollination hypothesis is ultimately about.",
    while_on_site=False,
    discriminates=(
        HypothesisClass.REWARD_BASED,
        HypothesisClass.FOOD_DECEPTION,
        HypothesisClass.SEXUAL_DECEPTION,
        HypothesisClass.AUTOGAMY,
    ),
)


TEMPLATES: tuple[HypothesisTemplate, ...] = (
    HypothesisTemplate(
        template_id="sexual-deception",
        hypothesis_class=HypothesisClass.SEXUAL_DECEPTION,
        ko_0038_strategy="sexual deception",
        statement=(
            "The {visitor} is responding to {subject} as a mating signal; any pollen transfer "
            "occurs during attempted copulation with the labellum rather than during feeding."
        ),
        predictions=(
            "Visitors are predominantly males of a single species.",
            "Contact is positioned on the labellum with the column touching a consistent body site.",
            "No feeding or reward collection is seen and visits are short.",
        ),
        would_support=(
            "Repeated male-only visits with copulatory posture.",
            "Pollinaria attached at a consistent body site across visitors.",
            "No visible nectar or oil.",
        ),
        would_contradict=(
            "Female visitors or mixed sexes feeding.",
            "Visible nectar that visitors consume.",
            "Pollen transfer by an unrelated visitor group.",
        ),
        positive_cues=frozenset(
            {
                _b(VisitorBehavior.PSEUDOCOPULATION_LIKE_CONTACT),
                _g(VisitorGroup.MALE_BEE),
                _g(VisitorGroup.MALE_WASP),
                _s(FloralSignalCue.INSECT_LIKE_LABELLUM),
                _r(RewardCheck.NECTAR_ABSENT),
            }
        ),
        question_family_ids=("signal-chemistry", "visual-chemical-tactile", "pollinator-specificity"),
        follow_ups=(
            _FU_COLUMN_CONTACT,
            _FU_VISITOR_SEX_ID,
            _FU_VISUAL_REWARD,
            _FU_SCENT_INTERVALS,
            _FU_FRUIT_SET_REVISIT,
        ),
    ),
    HypothesisTemplate(
        template_id="food-deception",
        hypothesis_class=HypothesisClass.FOOD_DECEPTION,
        ko_0038_strategy="food deception",
        statement=(
            "{subject} advertises a food reward through colour, shape or scent that it does not "
            "provide; the {visitor} probes for food, finds none, and departs."
        ),
        predictions=(
            "Visitors probe briefly and leave without feeding.",
            "A range of visitor groups is seen rather than one species.",
            "A rewarding co-flowering plant with a similar display is nearby.",
        ),
        would_support=(
            "Repeated probe-and-leave visits.",
            "No visible reward.",
            "The same visitors feeding on a similar-looking rewarding plant nearby.",
        ),
        would_contradict=(
            "Visible nectar or oil that visitors collect.",
            "Long feeding bouts with repeated returns.",
        ),
        positive_cues=frozenset(
            {
                _b(VisitorBehavior.PROBING_FOR_NECTAR),
                _r(RewardCheck.NECTAR_ABSENT),
                _s(FloralSignalCue.RESEMBLES_REWARDING_FLOWER_NEARBY),
                _g(VisitorGroup.BEE),
                _g(VisitorGroup.FLY),
                _g(VisitorGroup.BUTTERFLY),
                _g(VisitorGroup.MOTH),
            }
        ),
        question_family_ids=("reward-deception-transitions", "pollinator-specificity"),
        follow_ups=(_FU_VISUAL_REWARD, _FU_VISIT_DURATION, _FU_COFLOWERING, _FU_FRUIT_SET_REVISIT),
    ),
    HypothesisTemplate(
        template_id="brood-site-deception",
        hypothesis_class=HypothesisClass.BROOD_SITE_DECEPTION,
        ko_0038_strategy="brood-site deception",
        statement=(
            "{subject} imitates an egg-laying substrate; the {visitor} attempts to oviposit and "
            "contacts the column while doing so."
        ),
        predictions=(
            "Egg-laying attempts, eggs or larvae are found on the flower.",
            "Visitors are dominated by flies or fungus gnats.",
            "Odour or surface resembles decay, dung or fungus.",
        ),
        would_support=(
            "Eggs or larvae photographed on the labellum.",
            "Repeated oviposition attempts by one visitor group.",
        ),
        would_contradict=(
            "Visitors feed on a visible reward.",
            "No oviposition behaviour across many visits.",
        ),
        positive_cues=frozenset(
            {
                _b(VisitorBehavior.ATTEMPTED_OVIPOSITION),
                _g(VisitorGroup.FLY),
                _g(VisitorGroup.FUNGUS_GNAT),
                _s(FloralSignalCue.DARK_SPOTS_OR_FUNGAL_RESEMBLANCE),
                _s(FloralSignalCue.CARRION_OR_DUNG_ODOR),
            }
        ),
        question_family_ids=("signal-chemistry", "repeated-evolution"),
        follow_ups=(_FU_OVIPOSITION, _FU_SCENT_INTERVALS, _FU_COLUMN_CONTACT),
    ),
    HypothesisTemplate(
        template_id="shelter-mimicry",
        hypothesis_class=HypothesisClass.SHELTER_MIMICRY,
        ko_0038_strategy="shelter mimicry",
        statement=(
            "The {visitor} uses {subject} as shelter or a warm refuge; pollen transfer, if it "
            "happens, is incidental to entering and leaving the flower."
        ),
        predictions=(
            "Visitors remain inside the flower for long periods, especially in cool or wet weather.",
            "Visitors leave carrying pollinaria without having fed.",
        ),
        would_support=(
            "Long residence times correlated with poor weather.",
            "Warmth detectable inside the flower.",
        ),
        would_contradict=(
            "Short visits in fair weather.",
            "Feeding or collecting behaviour.",
        ),
        positive_cues=frozenset(
            {
                _b(VisitorBehavior.RESTING_OR_SHELTERING),
                _s(FloralSignalCue.WARMTH_DETECTED),
            }
        ),
        question_family_ids=("reward-deception-transitions",),
        follow_ups=(_FU_RESIDENCE_WEATHER, _FU_POLLINARIA_CHECK),
    ),
    HypothesisTemplate(
        template_id="reward-based",
        hypothesis_class=HypothesisClass.REWARD_BASED,
        ko_0038_strategy="reward-based",
        statement=(
            "{subject} provides a genuine reward (nectar, oil or fragrance compounds) that the "
            "{visitor} collects, and pollen transfer occurs during collection."
        ),
        predictions=(
            "Sustained feeding or collecting on a specific floral part.",
            "Repeated returns by the same individuals and by both sexes.",
        ),
        would_support=(
            "Visible nectar, oil or resin.",
            "Feeding or collecting bouts followed by pollinarium removal.",
        ),
        would_contradict=(
            "No visible reward across many flowers.",
            "Visitors leave immediately after a single probe.",
        ),
        positive_cues=frozenset(
            {
                _r(RewardCheck.NECTAR_PRESENT),
                _b(VisitorBehavior.POLLEN_OR_FRAGRANCE_COLLECTION),
                _s(FloralSignalCue.OIL_OR_RESIN_SECRETION),
                _g(VisitorGroup.EUGLOSSINE_BEE),
                _g(VisitorGroup.OIL_COLLECTING_BEE),
                _g(VisitorGroup.BIRD),
            }
        ),
        question_family_ids=("reward-deception-transitions", "reproductive-success"),
        follow_ups=(_FU_VISUAL_REWARD, _FU_VISIT_DURATION, _FU_COLUMN_CONTACT, _FU_FRUIT_SET_REVISIT),
    ),
    HypothesisTemplate(
        template_id="non-pollinating-visit",
        hypothesis_class=HypothesisClass.NON_POLLINATING_VISIT,
        ko_0038_strategy="unknown",
        statement=(
            "The {visitor} is not an effective pollinator of {subject}: the visit is incidental, "
            "predatory or thieving and does not move pollinia."
        ),
        predictions=(
            "No pollinarium removal or deposition follows visits.",
            "No consistent contact with the column.",
        ),
        would_support=(
            "Column photographed intact after many visits.",
            "Visitors never touch the column.",
        ),
        would_contradict=(
            "A pollinarium carried by a departing visitor.",
            "Pollinia deposited on the stigma after a visit.",
        ),
        positive_cues=frozenset({_b(VisitorBehavior.BRIEF_LANDING_NO_COLUMN_CONTACT)}),
        question_family_ids=("pollinator-specificity",),
        follow_ups=(_FU_POLLINARIA_CHECK, _FU_COLUMN_CONTACT),
        always_included_when=("a visitor was observed",),
    ),
    HypothesisTemplate(
        template_id="unobserved-pollinator",
        hypothesis_class=HypothesisClass.UNOBSERVED_POLLINATOR,
        ko_0038_strategy="unknown",
        statement=(
            "{subject} is pollinated by a visitor that was not present during this observation "
            "window, for example at dusk, at night or at dawn."
        ),
        predictions=(
            "Visits occur at other times of day.",
            "Scent, if any, is strongest outside the observed window.",
        ),
        would_support=(
            "Visitors recorded at other times.",
            "Pollinaria removed between visits with no visitor seen.",
        ),
        would_contradict=(
            "No visits across repeated sessions at all times of day.",
            "Fruit set in flowers that were never visited.",
        ),
        positive_cues=frozenset(),
        question_family_ids=("pollinator-specificity",),
        follow_ups=(_FU_OTHER_TIMES, _FU_SCENT_INTERVALS, _FU_POLLINARIA_CHECK),
        always_included_when=("no visitor was observed",),
    ),
    HypothesisTemplate(
        template_id="autogamy",
        hypothesis_class=HypothesisClass.AUTOGAMY,
        ko_0038_strategy="autogamy",
        statement=(
            "{subject} sets fruit by self-pollination without a visitor; pollinia reach the stigma "
            "within the flower."
        ),
        predictions=(
            "Fruit set occurs in flowers that receive no visits.",
            "Pollinia in aging flowers move toward or onto the stigma.",
        ),
        would_support=(
            "Photographs of unvisited flowers with pollinia on the stigma.",
            "Uniform fruit set regardless of visitor activity.",
        ),
        would_contradict=(
            "Fruit set only in visited flowers.",
            "Pollinia remain in place in aging unvisited flowers.",
        ),
        positive_cues=frozenset({_o(ReproductiveOutcomeCue.FRUIT_SET_OBSERVED)}),
        question_family_ids=("reproductive-success",),
        follow_ups=(_FU_AGING_COLUMN, _FU_FRUIT_SET_REVISIT),
        always_included_when=("no visitor was observed",),
    ),
    HypothesisTemplate(
        template_id="identification-uncertainty",
        hypothesis_class=HypothesisClass.IDENTIFICATION_UNCERTAINTY,
        ko_0038_strategy="unknown",
        statement=(
            "The orchid recorded as {subject}, or the {visitor}, is misidentified, so the "
            "interaction may belong to a different taxon pair than the observation implies."
        ),
        predictions=(
            "Diagnostic images reviewed against the canonical taxonomy resolve to a different taxon.",
            "The visitor group differs from the observer's first impression on review.",
        ),
        would_support=(
            "Reviewer identifies a different orchid taxon from diagnostic images.",
            "Visitor images reviewed to a different functional group.",
        ),
        would_contradict=(
            "Human review of diagnostic images confirms both identifications.",
        ),
        positive_cues=frozenset({_g(VisitorGroup.UNKNOWN), _g(VisitorGroup.OTHER)}),
        question_family_ids=(),
        follow_ups=(_FU_TAXON_DIAGNOSTICS, _FU_VISITOR_SEX_ID),
        always_included_when=("observer certainty is POSSIBLE or UNCERTAIN",),
    ),
)

_TEMPLATE_INDEX = {template.template_id: template for template in TEMPLATES}

#: When cue matching and the structural alternatives together still leave fewer
#: than two hypotheses, these two general classes are added in this order.
_FALLBACK_TEMPLATE_IDS: tuple[str, ...] = ("reward-based", "food-deception")

MAX_HYPOTHESES = 6


def template_by_id(template_id: str) -> HypothesisTemplate:
    return _TEMPLATE_INDEX[template_id]


def _always_included(template: HypothesisTemplate, snapshot: ObservationSnapshot) -> bool:
    interaction = snapshot.interaction
    if template.hypothesis_class == HypothesisClass.NON_POLLINATING_VISIT:
        return interaction.visitor_observed
    if template.hypothesis_class in {
        HypothesisClass.UNOBSERVED_POLLINATOR,
        HypothesisClass.AUTOGAMY,
    }:
        return not interaction.visitor_observed
    if template.hypothesis_class == HypothesisClass.IDENTIFICATION_UNCERTAINTY:
        return snapshot.epistemic_certainty in {
            ObserverCertainty.POSSIBLE,
            ObserverCertainty.UNCERTAIN,
        }
    return False


@dataclass(frozen=True)
class SelectedHypothesis:
    template: HypothesisTemplate
    cue_matches: tuple[str, ...]
    structural: bool


def select_hypotheses(snapshot: ObservationSnapshot) -> list[SelectedHypothesis]:
    """Deterministically choose the competing hypotheses for a snapshot.

    Always returns at least :data:`MINIMUM_COMPETING_HYPOTHESES` entries and at
    most :data:`MAX_HYPOTHESES`, ordered by cue-match count then library order.
    """
    tokens = set(cue_tokens(snapshot))
    selected: dict[str, SelectedHypothesis] = {}

    for template in TEMPLATES:
        matches = tuple(sorted(template.positive_cues & tokens))
        structural = _always_included(template, snapshot)
        # A visitor-dependent class cannot explain an observation with no visitor.
        if not snapshot.interaction.visitor_observed and template.hypothesis_class in {
            HypothesisClass.NON_POLLINATING_VISIT,
        }:
            continue
        if matches or structural:
            selected[template.template_id] = SelectedHypothesis(template, matches, structural)

    for template_id in _FALLBACK_TEMPLATE_IDS:
        if len(selected) >= 2:
            break
        if template_id not in selected:
            selected[template_id] = SelectedHypothesis(_TEMPLATE_INDEX[template_id], (), False)

    library_order = {template.template_id: index for index, template in enumerate(TEMPLATES)}
    ordered = sorted(
        selected.values(),
        key=lambda item: (-len(item.cue_matches), library_order[item.template.template_id]),
    )
    # Structural alternatives are never dropped by the cap; trim cue-only
    # matches from the bottom first.
    if len(ordered) > MAX_HYPOTHESES:
        keep_structural = [item for item in ordered if item.structural]
        others = [item for item in ordered if not item.structural]
        ordered = sorted(
            keep_structural + others[: max(0, MAX_HYPOTHESES - len(keep_structural))],
            key=lambda item: (-len(item.cue_matches), library_order[item.template.template_id]),
        )
    return ordered


def follow_up_protocol(selected: list[SelectedHypothesis]) -> list[FollowUpObservation]:
    """Union of the selected hypotheses' follow-ups, de-duplicated by step, on-site first."""
    seen: dict[str, FollowUp] = {}
    for item in selected:
        for follow_up in item.template.follow_ups:
            seen.setdefault(follow_up.step_id, follow_up)
    ordered = sorted(seen.values(), key=lambda fu: (not fu.while_on_site, fu.step_id))
    return [fu.to_schema() for fu in ordered]
