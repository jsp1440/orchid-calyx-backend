"""Proofs for the capability router and the provider-request reservoir.

Every test here traces to a defect observed live on issue #1502, whose receipts
read in sequence: leased, then
``route=tier=deep; model=claude-opus-5; reason=default=cheap;deep-complexity-signal``,
then ``{"reason": "BLOCKED_MONTHLY_BUDGET_EXCEEDED", "provider_called": false,
"state": "oc-blocked"}``. A deterministic task was sent to the most expensive
model available because its body contained the word "architecture", was denied
for budget, and was parked whole with no record of what it had wanted.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib

import pytest

from app.provider_reservoir import (
    CAPABILITIES,
    CapabilityUnknown,
    ProviderIntentRecord,
    ProviderRequestReservoir,
    classify_capabilities,
    redact,
    route_task,
    routing,
)
from app.provider_reservoir.reservoir import AuthorizationEnvelope, ReservoirState

_SCRIPTS = pathlib.Path(__file__).resolve().parents[1] / "scripts"


def _load_script(module_name: str):
    """Load a ``scripts/`` module the way the workflows run it: by path."""
    spec = importlib.util.spec_from_file_location(
        module_name, _SCRIPTS / f"{module_name}.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


#: A real lease receipt, in the shape the write-set verifier parses.
_RECONCILE_LEASE_COMMENT = "[OC-SWARM-V4] Dependency/resource lease claimed: `" + json.dumps(
    {
        "dependencies": [],
        "issue_number": 1,
        "lease_id": "jsp1440/orchid-calyx-backend:1:1:1",
        "material_fingerprint": "0" * 16,
        "reads": [],
        "schema": "oc.swarm-claim.v1",
        "writes": ["control-plane"],
    },
    sort_keys=True,
) + "`."

# The exact shape of the task that was misrouted: deterministic capabilities,
# prose full of the words that used to trigger escalation.
COGINT_BODY = """Architecture: Orchid-Continuum-Brain PR #151 and COGINT-001.

Implement the backend execution layer. This is a cross-repo migration touching
concurrency and a security boundary, and involves scientific inference.

OC-SWARM-CAPABILITY: taxonomy-resolution
OC-SWARM-CAPABILITY: literature-evidence-lookup
OC-SWARM-CAPABILITY: reasoning-map-assembly
OC-SWARM-CAPABILITY: contradiction-detection
"""


def intent(**overrides) -> ProviderIntentRecord:
    base = {
        "objective": "Explain an assembled pollination reasoning map to a learner.",
        "capability": "natural-language-explanation",
        "why_deterministic_insufficient": (
            "The map, its evidence states and its gaps are assembled locally, but "
            "nothing here can render them as connected prose."
        ),
        "provider": "claude",
        "alternatives_considered": ["structured field rendering", "stored template phrasing"],
        "expected_gain": "A non-specialist can follow the reasoning without reading the map.",
        "urgency": "routine",
        "blocking": False,
        "deterministic_fallback": "Present the structured reasoning map unchanged.",
        "affected_tasks": [1502],
    }
    base.update(overrides)
    return ProviderIntentRecord(**base)


# ---------------------------------------------------------------------------
# 1, 2 — capability decides the lane; difficulty does not
# ---------------------------------------------------------------------------


def test_a_complex_task_is_not_provider_dependent_just_for_being_complex():
    """The regression that sent #1502 to `claude-opus-5`.

    Every escalation word that used to promote a task is present in this body.
    None of them is a capability requirement.
    """
    routing = route_task({"number": 1502, "body": COGINT_BODY})

    assert routing.provider_free is True
    assert routing.blocking_provider_capabilities == []
    assert "taxonomy-resolution" in routing.deterministic_capabilities
    assert "reasoning-map-assembly" in routing.deterministic_capabilities


def test_provider_free_work_runs_when_no_provider_budget_exists():
    """Provider budget is irrelevant to work that needs no provider.

    The routing decision does not consult budget at all, which is the property
    that keeps deterministic work running while the monthly budget is exhausted.
    """
    routing = route_task({"number": 1502, "body": COGINT_BODY})
    assert routing.provider_free is True
    assert routing.has_deterministic_work is True
    assert routing.fully_blocked is False


def test_the_legacy_single_literal_still_routes_and_so_does_every_other_task():
    """The predicate this replaced matched only `reconcile`."""
    assert route_task({"number": 1, "body": "OC-SWARM-PROVIDER-FREE: reconcile"}).provider_free
    assert route_task(
        {"number": 2, "body": "OC-SWARM-PROVIDER-FREE: deterministic-fixture"}
    ).provider_free


def test_an_unclassified_capability_raises_rather_than_guessing_a_lane():
    """Guessing costs money one way and reports false success the other."""
    with pytest.raises(CapabilityUnknown):
        route_task({"number": 3, "body": "OC-SWARM-CAPABILITY: telepathy"})


def test_every_registered_capability_that_needs_a_provider_names_its_alternative():
    """A provider claim that cannot be re-examined is a claim that never expires."""
    for capability in CAPABILITIES.values():
        if capability.provider_required:
            assert capability.deterministic_alternative.strip()


# ---------------------------------------------------------------------------
# 4, 5 — denial parks only the provider-dependent part
# ---------------------------------------------------------------------------


def test_denial_parks_only_the_provider_subtask_and_the_rest_still_runs():
    body = COGINT_BODY + (
        "\nOC-SWARM-CAPABILITY: natural-language-explanation"
        "\nOC-SWARM-PROVIDER-OPTIONAL: natural-language-explanation\n"
    )
    routing = route_task({"number": 1502, "body": body})

    assert routing.provider_free is True, "the deterministic work must still run"
    assert routing.parked_capabilities == ["natural-language-explanation"]
    assert routing.blocking_provider_capabilities == []
    assert len(routing.deterministic_capabilities) == 4


def test_a_task_needing_only_a_provider_capability_parks_whole_and_says_so():
    routing = route_task(
        {"number": 4, "body": "OC-SWARM-CAPABILITY: natural-language-explanation"}
    )
    assert routing.provider_free is False
    assert routing.fully_blocked is True


def test_one_blocked_task_does_not_hold_up_unrelated_eligible_work():
    """Work-conserving: a blocking request holds its own tasks and nothing else."""
    reservoir = ProviderRequestReservoir()
    reservoir.submit(intent(blocking=True, affected_tasks=[4]))

    assert reservoir.blocking_tasks() == {4}

    unrelated = route_task({"number": 1502, "body": COGINT_BODY})
    assert unrelated.provider_free is True
    assert unrelated.issue_number not in reservoir.blocking_tasks()


def test_optional_enrichment_never_holds_a_task():
    reservoir = ProviderRequestReservoir()
    reservoir.submit(intent(blocking=False, affected_tasks=[1502]))
    assert reservoir.blocking_tasks() == set()


# ---------------------------------------------------------------------------
# 3 — intent is preserved
# ---------------------------------------------------------------------------


def test_intent_is_preserved_with_the_reasoning_a_denial_would_otherwise_destroy():
    record = intent().to_record()

    for required in (
        "objective",
        "capability",
        "why_deterministic_insufficient",
        "provider",
        "alternatives_considered",
        "expected_gain",
        "urgency",
        "blocking",
        "deterministic_fallback",
        "affected_tasks",
    ):
        assert record[required] not in (None, "", [])
    assert record["schema"] == "oc.provider-intent.v1"


@pytest.mark.parametrize(
    "field",
    ["objective", "why_deterministic_insufficient", "expected_gain", "deterministic_fallback"],
)
def test_an_intent_missing_its_reasoning_is_refused(field):
    with pytest.raises(ValueError, match=field):
        intent(**{field: "  "})


def test_an_intent_naming_no_alternative_is_refused():
    with pytest.raises(ValueError, match="alternatives_considered"):
        intent(alternatives_considered=[])


# ---------------------------------------------------------------------------
# 6, 7 — consolidation and batching, by capability
# ---------------------------------------------------------------------------


def test_duplicate_requests_consolidate_into_one():
    reservoir = ProviderRequestReservoir()
    first = reservoir.submit(intent(affected_tasks=[1502]))
    second = reservoir.submit(intent(affected_tasks=[1503]))

    assert first.key == second.key
    assert len(reservoir.entries()) == 1
    assert second.duplicate_count == 2
    assert second.affected_tasks == [1502, 1503], "both tasks wait on one answer"


def test_consolidation_is_by_capability_and_question_not_by_asking_task():
    reservoir = ProviderRequestReservoir()
    reservoir.submit(intent(objective="Explain map A.", affected_tasks=[1]))
    reservoir.submit(intent(objective="Explain map B.", affected_tasks=[2]))
    assert len(reservoir.entries()) == 2, "different questions are not duplicates"


def test_a_blocking_duplicate_upgrades_an_optional_request_but_not_the_reverse():
    reservoir = ProviderRequestReservoir()
    reservoir.submit(intent(blocking=False, affected_tasks=[1]))
    entry = reservoir.submit(intent(blocking=True, affected_tasks=[2]))
    assert entry.intent.blocking is True

    reservoir.submit(intent(blocking=False, affected_tasks=[3]))
    assert reservoir.get(entry.key).intent.blocking is True


def test_batching_groups_compatible_capability_requests():
    reservoir = ProviderRequestReservoir()
    reservoir.submit(intent(objective="Explain map A.", affected_tasks=[1]))
    reservoir.submit(intent(objective="Explain map B.", affected_tasks=[2]))
    reservoir.submit(
        intent(
            capability="literature-summarisation",
            objective="Summarise paper X.",
            why_deterministic_insufficient="No stored abstract or extracted fields exist.",
            alternatives_considered=["stored abstract", "extracted fields"],
            affected_tasks=[3],
        )
    )

    batches = reservoir.batches()

    assert set(batches) == {"natural-language-explanation", "literature-summarisation"}
    assert len(batches["natural-language-explanation"]) == 2
    assert len(batches["literature-summarisation"]) == 1


def test_a_deterministic_capability_is_refused_entry_to_the_reservoir():
    with pytest.raises(ValueError, match="deterministic"):
        ProviderRequestReservoir().submit(
            intent(
                capability="taxonomy-resolution",
                why_deterministic_insufficient="n/a",
                alternatives_considered=["n/a"],
            )
        )


# ---------------------------------------------------------------------------
# 8 — piggybacking stays inside an existing authorization
# ---------------------------------------------------------------------------


def test_piggyback_rides_an_authorization_that_already_covers_the_capability():
    reservoir = ProviderRequestReservoir()
    entry = reservoir.submit(intent())
    envelope = AuthorizationEnvelope(
        envelope_id="auth-1",
        capabilities=frozenset({"natural-language-explanation"}),
        remaining_slots=2,
    )

    allowed, note = reservoir.piggyback(entry.key, envelope)

    assert allowed is True
    assert "auth-1" in note
    assert reservoir.get(entry.key).state is ReservoirState.AUTHORIZED


def test_piggyback_may_not_widen_an_authorization_to_another_capability():
    reservoir = ProviderRequestReservoir()
    entry = reservoir.submit(intent())
    envelope = AuthorizationEnvelope(
        envelope_id="auth-1",
        capabilities=frozenset({"literature-summarisation"}),
        remaining_slots=5,
    )

    allowed, note = reservoir.piggyback(entry.key, envelope)

    assert allowed is False
    assert "outside authorization" in note
    assert reservoir.get(entry.key).state is not ReservoirState.AUTHORIZED


def test_piggyback_may_not_exceed_the_capacity_of_an_authorization():
    reservoir = ProviderRequestReservoir()
    entry = reservoir.submit(intent())
    spent = AuthorizationEnvelope(
        envelope_id="auth-1",
        capabilities=frozenset({"natural-language-explanation"}),
        remaining_slots=0,
    )

    allowed, note = reservoir.piggyback(entry.key, spent)

    assert allowed is False
    assert "no remaining slot" in note


# ---------------------------------------------------------------------------
# 9, 10 — cache first, re-evaluate before spending
# ---------------------------------------------------------------------------


def test_a_cached_result_prevents_a_repeat_call():
    first = ProviderRequestReservoir()
    entry = first.submit(intent())
    first.record_result(entry.key, "a plain-English explanation")

    second = ProviderRequestReservoir(cache=first.cache_snapshot())
    repeat = second.submit(intent(affected_tasks=[1504]))

    assert repeat.state is ReservoirState.CACHED
    assert repeat.result == "a plain-English explanation"
    assert second.pending() == [], "nothing is waiting on a provider"


def test_requests_are_reevaluated_provider_free_before_any_spending():
    """Evidence that landed since the request was made must be tried first."""
    reservoir = ProviderRequestReservoir()
    entry = reservoir.submit(intent(blocking=True, affected_tasks=[1502]))
    assert reservoir.blocking_tasks() == {1502}

    resolved = reservoir.reevaluate(
        lambda record: "rendered from a stored template"
        if record.capability == "natural-language-explanation"
        else None
    )

    assert resolved == [entry.key]
    assert reservoir.get(entry.key).state is ReservoirState.RESOLVED_DETERMINISTICALLY
    assert reservoir.blocking_tasks() == set(), "the task is no longer held"
    assert reservoir.pending() == []


def test_reevaluation_leaves_a_request_alone_when_local_evidence_still_falls_short():
    reservoir = ProviderRequestReservoir()
    entry = reservoir.submit(intent())
    assert reservoir.reevaluate(lambda _record: None) == []
    assert reservoir.get(entry.key).state is ReservoirState.PRESERVED


def test_a_result_reaches_every_task_that_was_waiting_on_it():
    reservoir = ProviderRequestReservoir()
    entry = reservoir.submit(intent(affected_tasks=[1502]))
    reservoir.submit(intent(affected_tasks=[1503]))
    reservoir.record_result(entry.key, "one answer")

    assert reservoir.results_for_task(1502) == {"natural-language-explanation": "one answer"}
    assert reservoir.results_for_task(1503) == {"natural-language-explanation": "one answer"}


# ---------------------------------------------------------------------------
# 11, 12 — locality and credentials never reach a persisted record or a payload
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "locality",
    [
        "seen at -8.1234, -35.6789 on the ridge",
        "lat=-8.1234 lng=-35.6789",
        "8°07'30\"S near the trail",
        "recorded at latitude: -8.98765",
    ],
)
def test_protected_locality_is_redacted_from_a_persisted_intent(locality):
    record = intent(objective=f"Explain the sighting {locality}").to_record()

    assert "-8.1234" not in record["objective"]
    assert "-35.6789" not in record["objective"]
    assert "locality withheld" in record["objective"]


def test_protected_locality_is_redacted_from_the_provider_payload():
    payload = intent(
        objective="Explain the sighting at -8.1234, -35.6789",
        expected_gain="Learner understands the site at lat=-8.1234 lng=-35.6789",
    ).payload_for_provider()

    serialized = str(payload)
    assert "-8.1234" not in serialized
    assert "-35.6789" not in serialized


def test_the_provider_payload_carries_no_submitter_or_task_identity():
    payload = intent().payload_for_provider()
    assert set(payload) == {"capability", "objective", "expected_gain"}


@pytest.mark.parametrize(
    "credential",
    [
        "ghp_" + "abcdefghijklmnopqrstuvwxyz0123456789",
        "github_" + "pat_11ABCDEFG0123456789_abcdefghijklmnop",
        "sk-abcdefghijklmnopqrstuvwxyz012345",
        "Bearer abcdefghijklmnopqrstuvwxyz0123456789",
        "-----BEGIN " + "RSA PRIVATE KEY-----",
        "AKIA" + "IOSFODNN7EXAMPLE",
    ],
)
def test_a_credential_is_refused_entry_to_a_persisted_intent(credential):
    """Refused, not scrubbed: scrubbing hides that something tried."""
    with pytest.raises(ValueError, match="credential-shaped"):
        intent(objective=f"Call the service with {credential}")


def test_a_credential_in_an_alternative_is_refused_too():
    with pytest.raises(ValueError, match="credential-shaped"):
        intent(alternatives_considered=["use ghp_" + "abcdefghijklmnopqrstuvwxyz0123456789"])


def test_redaction_leaves_ordinary_scientific_text_alone():
    text = "Pollinated by Eulaema meriana; 3 of 7 records confirm the association."
    assert redact(text) == text


# ---------------------------------------------------------------------------
# 13, 14 — no scientific mutation; completion needs evidence
# ---------------------------------------------------------------------------


def test_nothing_in_this_package_can_mutate_scientific_or_taxonomic_state():
    """The reservoir reasons about requests; it must not be able to act on data.

    Checked against the parsed syntax tree rather than the file text, so the word
    "requests" in a sentence is not mistaken for the HTTP library.
    """
    import ast
    import pathlib

    forbidden_modules = {
        "psycopg", "psycopg2", "sqlalchemy", "requests", "urllib", "urllib3",
        "httpx", "aiohttp", "subprocess", "socket", "shutil", "pickle",
    }
    # `compile` is deliberately absent: `re.compile` is how the redaction and
    # marker patterns are built, and it reaches nothing outside this process.
    forbidden_calls = {"system", "popen", "exec", "eval", "__import__"}

    offenders: list[str] = []
    for path in sorted(pathlib.Path("app/provider_reservoir").glob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in forbidden_modules:
                        offenders.append(f"{path.name}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                root = (node.module or "").split(".")[0]
                if root in forbidden_modules:
                    offenders.append(f"{path.name}: from {node.module} import ...")
            elif isinstance(node, ast.Call):
                func = node.func
                name = getattr(func, "attr", None) or getattr(func, "id", None)
                if name in forbidden_calls:
                    offenders.append(f"{path.name}: call to {name}()")

    assert offenders == [], f"package can reach outside itself: {offenders}"

    # No SQL verb appears in any string literal either, so nothing can be handed
    # to a cursor by a caller.
    for path in sorted(pathlib.Path("app/provider_reservoir").glob("*.py")):
        tree = ast.parse(path.read_text())
        literals = [
            node.value.upper()
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        ]
        for text in literals:
            for verb in ("INSERT INTO", "UPDATE ", "DELETE FROM", "DROP TABLE", "COMMIT;"):
                assert verb not in text, f"{path.name} carries SQL {verb!r}"


def test_a_reservoir_record_states_its_state_rather_than_implying_success():
    """Completion must rest on durable evidence, not on having run.

    Every entry carries the state it actually reached and a note saying how, so
    "the workflow was green" can never be mistaken for "the request was answered".
    """
    reservoir = ProviderRequestReservoir()
    entry = reservoir.submit(intent(blocking=True))
    record = reservoir.to_record()

    assert record["entries"][0]["state"] == "PRESERVED"
    assert record["blocking_tasks"] == [1502]
    assert record["pending_count"] == 1

    reservoir.defer(entry.key)
    assert reservoir.to_record()["entries"][0]["state"] == "DEFERRED"
    assert reservoir.to_record()["entries"][0]["resolution_note"]

    reservoir.record_result(entry.key, "answer")
    done = reservoir.to_record()["entries"][0]
    assert done["state"] == "EXECUTED"
    assert done["resolution_note"]


def test_classification_splits_a_mixed_task_rather_than_blocking_it():
    deterministic, provider = classify_capabilities(
        ["reasoning-map-assembly", "natural-language-explanation", "taxonomy-resolution"]
    )
    assert deterministic == ["reasoning-map-assembly", "taxonomy-resolution"]
    assert provider == ["natural-language-explanation"]


class TestLaneExecutabilityIsNotProviderFreedom:
    """Admission to the deterministic lane is a different question from routing.

    On 2026-09-19 at 01:04 the controller leased #1502 into the provider-free
    lane and the worker rejected it: "provider-free reconcile marker missing or
    unsupported". The issue went to ``oc-blocked``, a label that holds work
    outside the execution portfolio permanently. Nothing was blocking it. The
    lane had no executor for it, which is a different thing and has a different
    remedy.
    """

    #: #1502 as it actually stands, reduced to the lines routing reads.
    COGINT_BODY = """Architecture: Orchid-Continuum-Brain PR #151 and COGINT-001.
OC-SWARM-CAPABILITY: taxonomy-resolution
OC-SWARM-CAPABILITY: reasoning-map-assembly
OC-SWARM-CAPABILITY: contradiction-detection
OC-SWARM-CAPABILITY: natural-language-explanation
OC-SWARM-PROVIDER-OPTIONAL: natural-language-explanation"""

    def test_declared_capabilities_do_not_staff_the_lane(self) -> None:
        issue = {"number": 1502, "state": "OPEN", "body": self.COGINT_BODY}
        result = routing.route_task(issue)
        # Genuinely provider-free: nothing blocking needs a model.
        assert result.provider_free is True
        # And still not executable here, which is the distinction that was missing.
        assert result.lane_executable is False
        assert "not an executor that can do it" in (result.unexecutable_reason or "")

    def test_a_named_executor_that_exists_is_admitted(self) -> None:
        issue = {
            "number": 9001,
            "state": "OPEN",
            "body": "OC-SWARM-PROVIDER-FREE: reconcile\nOC-SWARM-DISPOSITION: done",
        }
        result = routing.route_task(issue)
        assert result.lane_executable is True
        assert result.executable_task == "reconcile"
        assert result.unexecutable_reason is None

    def test_a_named_executor_that_does_not_exist_is_refused_by_name(self) -> None:
        # The legacy marker accepts any task name since #1504. Accepting the
        # name is not the same as having the program, and the refusal has to say
        # which it is or the next reader repeats the 01:04 diagnosis.
        issue = {
            "number": 9002,
            "state": "OPEN",
            "body": "OC-SWARM-PROVIDER-FREE: rebuild-the-graph",
        }
        result = routing.route_task(issue)
        assert result.lane_executable is False
        assert "rebuild-the-graph" in (result.unexecutable_reason or "")
        assert "reconcile" in (result.unexecutable_reason or "")

    def test_every_advertised_executor_is_one_the_worker_accepts(self) -> None:
        """The registry may not promise an executor the worker will reject.

        This is the invariant whose absence caused the incident: the controller
        believed in a lane the worker did not implement.
        """
        worker = _load_script("oc_swarm_provider_free_worker")
        for task in routing.DETERMINISTIC_EXECUTORS:
            issue = {
                "number": 1,
                "state": "OPEN",
                "body": f"OC-SWARM-PROVIDER-FREE: {task}\nOC-SWARM-DISPOSITION: done",
            }
            # Must not raise the "missing or unsupported" marker error.
            receipt = worker.build_receipt(
                issue,
                lease_comment=_RECONCILE_LEASE_COMMENT,
                changed_files=[],
                integration_sha="0" * 40,
            )
            assert receipt["mode"] == task

    def test_unstaffed_work_is_not_recorded_as_blocked(self) -> None:
        controller = _load_script("oc_swarm_controller")
        refusal = controller.lane_refusal(
            {"number": 1502, "state": "OPEN", "body": self.COGINT_BODY}
        )
        assert refusal["schema"] == "oc.lane-refusal.v1"
        # The whole point: nothing is blocking this, so it keeps its place in
        # the portfolio instead of being labelled out of it.
        assert refusal["blocked"] is False
        assert refusal["provider_free"] is True
        assert refusal["lane_executable"] is False
        assert refusal["reason"]

    def test_unstaffed_work_is_not_handed_to_the_paid_lane_either(self) -> None:
        """Neither lane, and visible. Sending it to a provider is the old defect."""
        controller = _load_script("oc_swarm_controller")
        snapshot = {
            "max_active_lanes": 4,
            "issues": [
                {
                    "number": 1502,
                    "state": "OPEN",
                    "body": self.COGINT_BODY,
                    "labels": ["oc-queued", "oc-p0"],
                },
                {
                    "number": 9001,
                    "state": "OPEN",
                    "body": (
                        "OC-SWARM-PROVIDER-FREE: reconcile\nOC-SWARM-DISPOSITION: done"
                    ),
                    "labels": ["oc-queued", "oc-p1"],
                },
            ],
        }
        plan = controller.build_swarm_plan(snapshot, worker_slots=4)
        free = [w["issue_number"] for w in plan["provider_free_workers"]]
        paid = [w["issue_number"] for w in plan["provider_workers"]]
        unstaffed = plan["unstaffed_numbers"]

        assert 9001 in free, "an executor that exists must still be admitted"
        assert 1502 not in free, "the worker would reject this and blocked-label it"
        assert 1502 not in paid, "routing it to a provider is the defect #1504 repaired"
        assert 1502 in unstaffed
        assert plan["lane_refusals"][0]["issue_number"] == 1502

    def test_the_worker_split_refuses_unstaffed_work_on_its_own(self) -> None:
        """The withdrawal and the split must each hold without the other.

        Withdrawing unstaffed work from candidacy means it normally never
        reaches the lane split, which leaves the split's own guard unexercised —
        and an unexercised guard is a claim, not a property. So this removes the
        withdrawal and checks the split still refuses: if the two ever disagree,
        the task reaches the worker that marks it blocked.
        """
        controller = _load_script("oc_swarm_controller")
        controller.unstaffed_numbers = lambda snapshot: []
        snapshot = {
            "max_active_lanes": 4,
            "issues": [
                {
                    "number": 1502,
                    "state": "OPEN",
                    "body": self.COGINT_BODY,
                    "labels": ["oc-queued", "oc-p0"],
                }
            ],
        }
        plan = controller.build_swarm_plan(snapshot, worker_slots=4)
        assert plan["selected_numbers"] == [1502], "withdrawal is disabled here"
        assert [w["issue_number"] for w in plan["provider_free_workers"]] == []
        assert all(w["lane_executable"] for w in plan["provider_free_workers"])

    def test_one_unstaffed_task_does_not_starve_an_executable_one(self) -> None:
        """Work-conserving: the lane still runs what it can."""
        controller = _load_script("oc_swarm_controller")
        snapshot = {
            "max_active_lanes": 4,
            "issues": [
                {
                    "number": 1502,
                    "state": "OPEN",
                    "body": self.COGINT_BODY,
                    "labels": ["oc-queued", "oc-p0"],
                },
                {
                    "number": 9001,
                    "state": "OPEN",
                    "body": (
                        "OC-SWARM-PROVIDER-FREE: reconcile\nOC-SWARM-DISPOSITION: done"
                    ),
                    "labels": ["oc-queued", "oc-p4"],
                },
            ],
        }
        plan = controller.build_swarm_plan(snapshot, worker_slots=4)
        # #1502 outranks it at P0 and cannot run; the P4 task must still launch.
        assert plan["provider_free_launch_count"] == 1
        assert plan["provider_free_workers"][0]["issue_number"] == 9001
