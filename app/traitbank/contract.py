"""The backend's TraitBank is the Brain's ``oc-traitbank-v1`` contract, pinned.

Two Brain artifacts are vendored verbatim and pinned by sha256, the same way
``contracts/decision_fabric_v1.json`` is:

- ``contracts/traitbank_v1.json`` from Orchid-Continuum-Brain PR #246
  (commit 2f5623212b603c3026e23255b39f126a132ea69e);
- ``contracts/brain/OAO_Term_Registry.csv`` from Orchid-Continuum-Brain
  ``main`` (last changed in f65a4501cd33be5e772ace6a3b129581831c5e1d), the
  canonical Orchid Anatomy Ontology registry. It is read, never extended:
  new OAO terms are minted in the Brain, then re-vendored here.

A drifted file is refused rather than loaded.
"""

from __future__ import annotations

import csv
import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "contracts" / "traitbank_v1.json"
OAO_REGISTRY_PATH = ROOT / "contracts" / "brain" / "OAO_Term_Registry.csv"
BRAIN_CONTRACT_SHA256 = (
    "974847e1e34119e19389c48d4af9ea2e5cb66eb6ea7245314f74285921e8243d"
)
BRAIN_OAO_REGISTRY_SHA256 = (
    "739574ce7bb717ab10f60002ab3ac312bd46b3dadf63186809702fbddcce40ba"
)
BRAIN_CONTRACT_COMMIT = "2f5623212b603c3026e23255b39f126a132ea69e"
CONTRACT_VERSION = "oc-traitbank-v1"


class TraitBankContractError(RuntimeError):
    """The vendored Brain artifact does not match its pin."""


def _pinned_bytes(path: Path, expected: str) -> bytes:
    data = path.read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        raise TraitBankContractError(
            f"{path.name} drifted from its Brain pin: {actual} != {expected}"
        )
    return data


def load_contract(
    path: Path = CONTRACT_PATH, expected_sha256: str = BRAIN_CONTRACT_SHA256
) -> dict[str, Any]:
    contract = json.loads(_pinned_bytes(path, expected_sha256))
    if contract.get("contract_version") != CONTRACT_VERSION:
        raise TraitBankContractError("unexpected contract_version")
    governance = contract.get("governance") or {}
    for flag in (
        "automatic_scientific_publication_allowed",
        "graph_mutation_allowed",
        "database_write_allowed",
        "taxonomy_creation_allowed",
        "correlation_may_be_presented_as_adaptation",
        "breeding_prediction_enabled",
    ):
        if governance.get(flag) is not False:
            raise TraitBankContractError(f"governance.{flag} must be false")
    if governance.get("human_review_required") is not True:
        raise TraitBankContractError("governance.human_review_required must be true")
    return contract


def load_oao_terms(
    path: Path = OAO_REGISTRY_PATH, expected_sha256: str = BRAIN_OAO_REGISTRY_SHA256
) -> dict[str, dict[str, str]]:
    text = _pinned_bytes(path, expected_sha256).decode("utf-8")
    return {
        row["oao_id"]: row
        for row in csv.DictReader(text.splitlines())
        if str(row.get("active", "")).strip().lower() == "true"
    }


@lru_cache(maxsize=1)
def contract() -> dict[str, Any]:
    return load_contract()


@lru_cache(maxsize=1)
def oao_terms() -> dict[str, dict[str, str]]:
    return load_oao_terms()


def vocabulary(name: str) -> tuple[str, ...]:
    return tuple(contract()["vocabularies"][name])
