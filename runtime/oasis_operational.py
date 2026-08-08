"""Bounded OASIS greenhouse decision-support engine for CALYX issue #452.

OASIS evaluates deterministic environmental rules and records recommendations. It does
not control equipment, prescribe pesticides, publish science, or mutate the Knowledge
Graph. Owner-scoped plant identity and care history remain delegated to Conservatory.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from runtime.conservatory_operational import ConservatoryService

OASIS_SCHEMA_VERSION = "calyx-oasis/v1"
METRICS = {"temperature_c", "humidity_pct", "light_ppfd", "substrate_moisture_pct", "ventilation_state"}
RULES = {"temperature", "humidity", "light", "watering", "ventilation"}
EvidenceState = Literal["measured", "derived", "insufficient"]
Severity = Literal["info", "watch", "action"]


def _text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _stable(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def oasis_root() -> Path:
    return Path(os.getenv("CALYX_OASIS_DIR", "/tmp/calyx/oasis"))


@dataclass(frozen=True)
class GrowingSpace:
    space_id: str
    label: str
    conservatory_location_id: str
    notes: str | None = None


@dataclass(frozen=True)
class Sensor:
    sensor_id: str
    space_id: str
    metric: str
    unit: str
    source: str


@dataclass(frozen=True)
class Threshold:
    rule: str
    minimum: float | None = None
    maximum: float | None = None
    target: float | None = None
    tolerance: float | None = None
    evidence_note: str | None = None


@dataclass(frozen=True)
class Observation:
    observation_id: str
    sensor_id: str
    space_id: str
    metric: str
    value: float | str
    observed_at: str
    quality: str = "accepted"


@dataclass(frozen=True)
class Recommendation:
    recommendation_id: str
    plant_id: str
    space_id: str
    rule: str
    severity: Severity
    action: str
    rationale: str
    evidence_state: EvidenceState
    uncertainty: float
    evidence_observation_ids: tuple[str, ...]
    repeat_key: str
    created_at: str
    suppressed: bool = False
    suppression_reason: str | None = None
    acknowledged: bool = False


@dataclass(frozen=True)
class Intervention:
    intervention_id: str
    recommendation_id: str
    plant_id: str
    intervention_type: str
    performed_at: str
    notes: str | None
    actor: str


@dataclass(frozen=True)
class Outcome:
    outcome_id: str
    intervention_id: str
    recorded_at: str
    state: str
    notes: str | None


class OasisService:
    def __init__(
        self,
        workspace: Path | None = None,
        *,
        conservatory: ConservatoryService | None = None,
    ) -> None:
        self.workspace = workspace or oasis_root()
        self.conservatory = conservatory or ConservatoryService()

    @staticmethod
    def _owner_key(owner_id: str) -> str:
        owner = _text(owner_id)
        if not owner:
            raise ValueError("OASIS_OWNER_REQUIRED")
        return _sha(owner.casefold())[:24]

    def _root(self, owner_id: str) -> Path:
        return self.workspace / "owners" / self._owner_key(owner_id)

    @staticmethod
    def _path(root: Path, kind: str, record_id: str) -> Path:
        clean = _text(record_id)
        if not clean or "/" in clean or "\\" in clean or ".." in clean:
            raise ValueError("OASIS_RECORD_ID_INVALID")
        return root / kind / f"{clean}.json"

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(path.stem)
        return json.loads(path.read_text(encoding="utf-8"))

    def configure_space(self, owner_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        root = self._root(owner_id)
        space = GrowingSpace(
            space_id=_text(payload.get("space_id")),
            label=_text(payload.get("label")),
            conservatory_location_id=_text(payload.get("conservatory_location_id")),
            notes=_text(payload.get("notes")) or None,
        )
        if not all((space.space_id, space.label, space.conservatory_location_id)):
            raise ValueError("OASIS_SPACE_FIELDS_REQUIRED")
        # Resolve location through the owner-scoped Conservatory dossier boundary.
        _, conservatory_root = self.conservatory._owner_root(owner_id)
        self.conservatory._location(conservatory_root, space.conservatory_location_id)
        record = {**asdict(space), "schema_version": OASIS_SCHEMA_VERSION, "private": True}
        path = self._path(root, "spaces", space.space_id)
        if path.exists():
            existing = self._read(path)
            if existing != record:
                raise ValueError("OASIS_SPACE_IMMUTABLE_CONFLICT")
            return {"created": False, "space": existing}
        _atomic(path, record)
        return {"created": True, "space": record}

    def register_sensor(self, owner_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        root = self._root(owner_id)
        sensor = Sensor(
            sensor_id=_text(payload.get("sensor_id")),
            space_id=_text(payload.get("space_id")),
            metric=_text(payload.get("metric")).casefold(),
            unit=_text(payload.get("unit")),
            source=_text(payload.get("source")),
        )
        if not all((sensor.sensor_id, sensor.space_id, sensor.metric, sensor.unit, sensor.source)):
            raise ValueError("OASIS_SENSOR_FIELDS_REQUIRED")
        if sensor.metric not in METRICS:
            raise ValueError("OASIS_SENSOR_METRIC_INVALID")
        self._read(self._path(root, "spaces", sensor.space_id))
        record = {**asdict(sensor), "schema_version": OASIS_SCHEMA_VERSION}
        path = self._path(root, "sensors", sensor.sensor_id)
        if path.exists():
            existing = self._read(path)
            if existing != record:
                raise ValueError("OASIS_SENSOR_IMMUTABLE_CONFLICT")
            return {"created": False, "sensor": existing}
        _atomic(path, record)
        return {"created": True, "sensor": record}

    def set_thresholds(self, owner_id: str, plant_id: str, thresholds: list[dict[str, Any]]) -> dict[str, Any]:
        root = self._root(owner_id)
        self.conservatory.dossier(owner_id, plant_id)
        records: list[dict[str, Any]] = []
        seen: set[str] = set()
        for payload in thresholds:
            rule = _text(payload.get("rule")).casefold()
            if rule not in RULES or rule in seen:
                raise ValueError("OASIS_THRESHOLD_RULE_INVALID_OR_DUPLICATE")
            seen.add(rule)
            threshold = Threshold(
                rule=rule,
                minimum=float(payload["minimum"]) if payload.get("minimum") is not None else None,
                maximum=float(payload["maximum"]) if payload.get("maximum") is not None else None,
                target=float(payload["target"]) if payload.get("target") is not None else None,
                tolerance=float(payload["tolerance"]) if payload.get("tolerance") is not None else None,
                evidence_note=_text(payload.get("evidence_note")) or None,
            )
            if threshold.minimum is None and threshold.maximum is None and threshold.target is None:
                raise ValueError("OASIS_THRESHOLD_VALUE_REQUIRED")
            if threshold.minimum is not None and threshold.maximum is not None and threshold.minimum > threshold.maximum:
                raise ValueError("OASIS_THRESHOLD_RANGE_INVALID")
            records.append(asdict(threshold))
        record = {
            "schema_version": OASIS_SCHEMA_VERSION,
            "plant_id": plant_id,
            "thresholds": records,
            "advisory_only": True,
        }
        _atomic(self._path(root, "thresholds", plant_id), record)
        return record

    def assign_plant(self, owner_id: str, plant_id: str, space_id: str) -> dict[str, Any]:
        root = self._root(owner_id)
        dossier = self.conservatory.dossier(owner_id, plant_id)
        space = self._read(self._path(root, "spaces", space_id))
        if dossier["plant"]["current_location_id"] != space["conservatory_location_id"]:
            raise ValueError("OASIS_PLANT_LOCATION_MISMATCH")
        record = {
            "schema_version": OASIS_SCHEMA_VERSION,
            "plant_id": plant_id,
            "space_id": space_id,
            "conservatory_location_id": space["conservatory_location_id"],
        }
        _atomic(self._path(root, "assignments", plant_id), record)
        return record

    def observe(self, owner_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        root = self._root(owner_id)
        sensor_id = _text(payload.get("sensor_id"))
        sensor = self._read(self._path(root, "sensors", sensor_id))
        observed_at = _text(payload.get("observed_at"))
        if not observed_at:
            raise ValueError("OASIS_OBSERVATION_TIME_REQUIRED")
        value: float | str
        if sensor["metric"] == "ventilation_state":
            value = _text(payload.get("value")).casefold()
            if value not in {"open", "closed", "on", "off", "unknown"}:
                raise ValueError("OASIS_VENTILATION_STATE_INVALID")
        else:
            value = float(payload.get("value"))
        material = _stable({"sensor_id": sensor_id, "observed_at": observed_at, "value": value})
        observation = Observation(
            observation_id=f"obs-{_sha(material)[:20]}",
            sensor_id=sensor_id,
            space_id=sensor["space_id"],
            metric=sensor["metric"],
            value=value,
            observed_at=observed_at,
            quality=_text(payload.get("quality") or "accepted").casefold(),
        )
        record = {**asdict(observation), "schema_version": OASIS_SCHEMA_VERSION}
        path = self._path(root, "observations", observation.observation_id)
        if path.exists():
            return {"created": False, "observation": self._read(path)}
        _atomic(path, record)
        return {"created": True, "observation": record}

    def _latest_observations(self, root: Path, space_id: str) -> dict[str, dict[str, Any]]:
        directory = root / "observations"
        latest: dict[str, dict[str, Any]] = {}
        if not directory.exists():
            return latest
        for path in directory.glob("*.json"):
            record = json.loads(path.read_text(encoding="utf-8"))
            if record.get("space_id") != space_id or record.get("quality") != "accepted":
                continue
            metric = record["metric"]
            current = latest.get(metric)
            if current is None or str(record["observed_at"]) > str(current["observed_at"]):
                latest[metric] = record
        return latest

    @staticmethod
    def _severity(delta: float, span: float) -> Severity:
        if delta <= 0:
            return "info"
        return "action" if delta >= max(span, 1.0) else "watch"

    @staticmethod
    def _numeric_rule(rule: str, threshold: dict[str, Any], observation: dict[str, Any] | None) -> tuple[str | None, str, Severity, float]:
        if observation is None:
            return "Collect a current measurement before changing care.", "No accepted current measurement is available.", "watch", 1.0
        value = float(observation["value"])
        minimum = threshold.get("minimum")
        maximum = threshold.get("maximum")
        target = threshold.get("target")
        tolerance = threshold.get("tolerance") or 0.0
        if minimum is not None and value < minimum:
            delta = float(minimum) - value
            action = {
                "temperature": "Move to a warmer microclimate or reduce avoidable heat loss.",
                "humidity": "Increase local humidity using non-chemical cultural measures.",
                "light": "Increase light exposure gradually while monitoring plant response.",
                "watering": "Review substrate moisture and consider watering if the medium is appropriately dry.",
            }[rule]
            return action, f"Observed {value:g} is below configured minimum {minimum:g}.", OasisService._severity(delta, abs(float(minimum)) * 0.1), min(1.0, 0.15 + delta / max(abs(float(minimum)), 1.0))
        if maximum is not None and value > maximum:
            delta = value - float(maximum)
            action = {
                "temperature": "Reduce heat load with shading or passive ventilation where appropriate.",
                "humidity": "Increase air movement and reduce prolonged excess humidity where appropriate.",
                "light": "Reduce light exposure or add shading while monitoring plant response.",
                "watering": "Delay watering and reassess substrate moisture before the next irrigation.",
            }[rule]
            return action, f"Observed {value:g} is above configured maximum {maximum:g}.", OasisService._severity(delta, abs(float(maximum)) * 0.1), min(1.0, 0.15 + delta / max(abs(float(maximum)), 1.0))
        if target is not None and abs(value - float(target)) > float(tolerance):
            delta = abs(value - float(target)) - float(tolerance)
            return "Monitor trend and adjust cultural conditions gradually toward the configured target.", f"Observed {value:g} differs from target {target:g} beyond tolerance {tolerance:g}.", "watch", min(0.8, 0.2 + delta / max(abs(float(target)), 1.0))
        return None, "Measurement is within the configured advisory range.", "info", 0.05

    def evaluate(self, owner_id: str, plant_id: str, *, evaluated_at: str) -> dict[str, Any]:
        root = self._root(owner_id)
        assignment = self._read(self._path(root, "assignments", plant_id))
        threshold_record = self._read(self._path(root, "thresholds", plant_id))
        observations = self._latest_observations(root, assignment["space_id"])
        emitted: list[dict[str, Any]] = []
        all_results: list[dict[str, Any]] = []
        metric_by_rule = {
            "temperature": "temperature_c",
            "humidity": "humidity_pct",
            "light": "light_ppfd",
            "watering": "substrate_moisture_pct",
        }
        for threshold in threshold_record["thresholds"]:
            rule = threshold["rule"]
            if rule == "ventilation":
                temp = observations.get("temperature_c")
                humidity = observations.get("humidity_pct")
                vent = observations.get("ventilation_state")
                evidence = [item["observation_id"] for item in (temp, humidity, vent) if item]
                if not temp and not humidity:
                    action, rationale, severity, uncertainty = (
                        "Collect temperature or humidity evidence before changing ventilation.",
                        "Ventilation evaluation lacks accepted environmental measurements.",
                        "watch",
                        1.0,
                    )
                else:
                    high_temp = threshold.get("maximum") is not None and temp and float(temp["value"]) > float(threshold["maximum"])
                    high_humidity = threshold.get("target") is not None and humidity and float(humidity["value"]) > float(threshold["target"])
                    vent_closed = vent is None or str(vent["value"]) in {"closed", "off", "unknown"}
                    if (high_temp or high_humidity) and vent_closed:
                        action = "Consider passive ventilation or increased air movement if safe for the growing space."
                        rationale = "Heat or humidity exceeds the configured ventilation trigger while ventilation is not confirmed active."
                        severity, uncertainty = "action", 0.25 if vent else 0.45
                    else:
                        action, rationale, severity, uncertainty = None, "Ventilation trigger conditions are not currently met.", "info", 0.15
                evidence_state: EvidenceState = "measured" if evidence else "insufficient"
            else:
                metric = metric_by_rule[rule]
                observation = observations.get(metric)
                action, rationale, severity, uncertainty = self._numeric_rule(rule, threshold, observation)
                evidence = [observation["observation_id"]] if observation else []
                evidence_state = "measured" if observation else "insufficient"

            if action is None:
                all_results.append({"rule": rule, "state": "within_range", "rationale": rationale})
                continue
            repeat_key = f"{plant_id}:{rule}:{action}"
            rec_material = _stable({"repeat_key": repeat_key, "evaluated_at": evaluated_at, "evidence": evidence})
            recommendation_id = f"rec-{_sha(rec_material)[:20]}"
            suppressed, suppression_reason = self._suppression(root, repeat_key, evaluated_at)
            rec = Recommendation(
                recommendation_id=recommendation_id,
                plant_id=plant_id,
                space_id=assignment["space_id"],
                rule=rule,
                severity=severity,
                action=action,
                rationale=rationale,
                evidence_state=evidence_state,
                uncertainty=round(float(uncertainty), 3),
                evidence_observation_ids=tuple(evidence),
                repeat_key=repeat_key,
                created_at=evaluated_at,
                suppressed=suppressed,
                suppression_reason=suppression_reason,
            )
            record = {**asdict(rec), "schema_version": OASIS_SCHEMA_VERSION, "advisory_only": True}
            _atomic(self._path(root, "recommendations", recommendation_id), record)
            all_results.append(record)
            if not suppressed:
                emitted.append(record)
        return {
            "plant_id": plant_id,
            "space_id": assignment["space_id"],
            "recommendations": emitted,
            "all_results": all_results,
            "autonomous_equipment_control": False,
            "medical_or_pesticide_prescribing": False,
            "scientific_publication_authorized": False,
            "knowledge_graph_mutation_authorized": False,
        }

    def _suppression(self, root: Path, repeat_key: str, evaluated_at: str) -> tuple[bool, str | None]:
        controls = root / "alert-controls"
        if controls.exists():
            for path in controls.glob("*.json"):
                record = json.loads(path.read_text(encoding="utf-8"))
                if record.get("repeat_key") != repeat_key:
                    continue
                until = record.get("suppress_until")
                if until and str(evaluated_at) <= str(until):
                    return True, "suppressed_until"
                if record.get("acknowledged") and not record.get("repeat_enabled", True):
                    return True, "acknowledged_repeat_disabled"
        return False, None

    def acknowledge(
        self,
        owner_id: str,
        recommendation_id: str,
        *,
        actor: str,
        acknowledged_at: str,
        suppress_until: str | None = None,
        repeat_enabled: bool = True,
    ) -> dict[str, Any]:
        root = self._root(owner_id)
        recommendation = self._read(self._path(root, "recommendations", recommendation_id))
        record = {
            "schema_version": OASIS_SCHEMA_VERSION,
            "recommendation_id": recommendation_id,
            "repeat_key": recommendation["repeat_key"],
            "acknowledged": True,
            "actor": _text(actor),
            "acknowledged_at": _text(acknowledged_at),
            "suppress_until": _text(suppress_until) or None,
            "repeat_enabled": bool(repeat_enabled),
        }
        if not record["actor"] or not record["acknowledged_at"]:
            raise ValueError("OASIS_ACKNOWLEDGEMENT_FIELDS_REQUIRED")
        _atomic(self._path(root, "alert-controls", recommendation_id), record)
        recommendation["acknowledged"] = True
        _atomic(self._path(root, "recommendations", recommendation_id), recommendation)
        return record

    def record_intervention(
        self,
        owner_id: str,
        recommendation_id: str,
        *,
        intervention_type: str,
        performed_at: str,
        actor: str,
        notes: str | None = None,
        handoff_to_conservatory: bool = True,
    ) -> dict[str, Any]:
        root = self._root(owner_id)
        rec = self._read(self._path(root, "recommendations", recommendation_id))
        intervention_type = _text(intervention_type).casefold()
        if intervention_type not in {"watering", "ventilation", "shading", "relocation", "monitoring", "other"}:
            raise ValueError("OASIS_INTERVENTION_TYPE_INVALID")
        material = _stable({"recommendation_id": recommendation_id, "type": intervention_type, "performed_at": performed_at, "actor": actor})
        intervention = Intervention(
            intervention_id=f"int-{_sha(material)[:20]}",
            recommendation_id=recommendation_id,
            plant_id=rec["plant_id"],
            intervention_type=intervention_type,
            performed_at=_text(performed_at),
            notes=_text(notes) or None,
            actor=_text(actor),
        )
        if not intervention.performed_at or not intervention.actor:
            raise ValueError("OASIS_INTERVENTION_FIELDS_REQUIRED")
        record = {**asdict(intervention), "schema_version": OASIS_SCHEMA_VERSION}
        _atomic(self._path(root, "interventions", intervention.intervention_id), record)
        handoff = None
        if handoff_to_conservatory:
            handoff = self.conservatory.add_event(
                owner_id,
                rec["plant_id"],
                event_type="treatment",
                occurred_at=intervention.performed_at,
                details={
                    "source": "OASIS",
                    "oasis_intervention_id": intervention.intervention_id,
                    "intervention_type": intervention.intervention_type,
                    "notes": intervention.notes,
                    "recommendation_id": recommendation_id,
                },
            )
        return {
            "intervention": record,
            "conservatory_handoff": handoff,
            "autonomous_equipment_control": False,
        }

    def record_outcome(
        self,
        owner_id: str,
        intervention_id: str,
        *,
        recorded_at: str,
        state: str,
        notes: str | None = None,
    ) -> dict[str, Any]:
        root = self._root(owner_id)
        self._read(self._path(root, "interventions", intervention_id))
        material = _stable({"intervention_id": intervention_id, "recorded_at": recorded_at, "state": state})
        outcome = Outcome(
            outcome_id=f"out-{_sha(material)[:20]}",
            intervention_id=intervention_id,
            recorded_at=_text(recorded_at),
            state=_text(state).casefold(),
            notes=_text(notes) or None,
        )
        if outcome.state not in {"improved", "unchanged", "worsened", "unknown"} or not outcome.recorded_at:
            raise ValueError("OASIS_OUTCOME_INVALID")
        record = {**asdict(outcome), "schema_version": OASIS_SCHEMA_VERSION}
        _atomic(self._path(root, "outcomes", outcome.outcome_id), record)
        return record

    def status(self, owner_id: str) -> dict[str, Any]:
        root = self._root(owner_id)

        def count(kind: str) -> int:
            directory = root / kind
            return len(list(directory.glob("*.json"))) if directory.exists() else 0

        return {
            "schema_version": OASIS_SCHEMA_VERSION,
            "spaces": count("spaces"),
            "sensors": count("sensors"),
            "observations": count("observations"),
            "recommendations": count("recommendations"),
            "interventions": count("interventions"),
            "outcomes": count("outcomes"),
            "advisory_only": True,
            "autonomous_equipment_control": False,
            "medical_or_pesticide_prescribing": False,
            "production_deployment_authorized": False,
            "scientific_publication_authorized": False,
            "knowledge_graph_mutation_authorized": False,
            "decision": "OASIS_PRIVATE_REVIEW_READY",
        }
