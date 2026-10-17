"""Read-only discovery over FIL capability descriptors.

This is an index of descriptions, not a registry of what exists: existence and
provider requirement come from :mod:`app.provider_reservoir.capabilities`, and
evidence-pinned eligibility from :mod:`runtime.brain_capability_registry`, which
this module consults rather than restates. It grants no execution authority.
"""

from __future__ import annotations

from typing import Any

from runtime.brain_capability_registry import CapabilityRegistry

from .contracts import CapabilityDescriptor, ContractError, OperatorClass
from .ontology import is_subtype, require_type


class FunctionalRegistry:
    def __init__(
        self,
        descriptors: tuple[CapabilityDescriptor, ...],
        *,
        brain_registry: CapabilityRegistry | None = None,
    ) -> None:
        items: dict[str, CapabilityDescriptor] = {}
        for descriptor in descriptors:
            if descriptor.capability_id in items:
                raise ContractError(
                    f"DUPLICATE_CAPABILITY_ID:{descriptor.capability_id}"
                )
            for port in (*descriptor.inputs, *descriptor.outputs):
                require_type(port.semantic_type)
            items[descriptor.capability_id] = descriptor
        self._items = dict(sorted(items.items()))
        self._brain_registry = brain_registry

    def __len__(self) -> int:
        return len(self._items)

    def get(self, capability_id: str) -> CapabilityDescriptor:
        try:
            return self._items[capability_id]
        except KeyError as exc:
            raise ContractError(f"UNKNOWN_FIL_CAPABILITY:{capability_id}") from exc

    def descriptors(self) -> tuple[CapabilityDescriptor, ...]:
        return tuple(self._items.values())

    def discover(
        self,
        *,
        consumes: str | None = None,
        produces: str | None = None,
        operator_class: OperatorClass | None = None,
        registry_capability: str | None = None,
    ) -> tuple[CapabilityDescriptor, ...]:
        """Descriptors matching every given filter, in capability-id order.

        ``consumes`` matches a function that can accept an artifact of that type
        (its input type is the type or an ancestor); ``produces`` matches a
        function whose output is the type or a subtype.
        """

        if consumes is not None:
            require_type(consumes)
        if produces is not None:
            require_type(produces)
        found = []
        for descriptor in self._items.values():
            if consumes is not None and not any(
                is_subtype(consumes, port.semantic_type) for port in descriptor.inputs
            ):
                continue
            if produces is not None and not any(
                is_subtype(port.semantic_type, produces) for port in descriptor.outputs
            ):
                continue
            if (
                operator_class is not None
                and descriptor.operator_class is not operator_class
            ):
                continue
            if (
                registry_capability is not None
                and descriptor.registry_capability != registry_capability
            ):
                continue
            found.append(descriptor)
        return tuple(found)

    def brain_eligibility(self, capability_id: str) -> dict[str, Any] | None:
        """The Brain registry's verdict for a linked descriptor, unmodified.

        ``None`` when the descriptor names no Brain capability. When it names one
        and no Brain registry was supplied, the answer is an explicit refusal
        rather than an assumed pass.
        """

        descriptor = self.get(capability_id)
        if descriptor.brain_capability_id is None:
            return None
        if self._brain_registry is None:
            return {
                "capability_id": descriptor.brain_capability_id,
                "eligible": False,
                "reasons": ["brain capability registry not supplied"],
            }
        return self._brain_registry.eligibility(descriptor.brain_capability_id)

    def view(self) -> dict[str, Any]:
        """Stable, read-only snapshot for operators and tests."""
        return {
            "contract": "oc.fil.registry-view.v1",
            "read_only": True,
            "execution_authority": False,
            "publication_authority": False,
            "capabilities": [
                {
                    **descriptor.to_dict(),
                    "brain_eligibility": self.brain_eligibility(
                        descriptor.capability_id
                    ),
                }
                for descriptor in self._items.values()
            ],
        }
