from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import entry_points
from typing import Any, Protocol


class BrainConnector(Protocol):
    id: str
    name: str
    version: str
    capabilities: tuple[str, ...]

    def execute(self, action: str, payload: dict[str, Any]) -> dict[str, Any]: ...
    def health(self) -> dict[str, Any]: ...


class ConnectorRegistry:
    """Explicit registry with optional Python entry-point discovery.

    Third-party packages may expose a connector instance or zero-argument
    factory in the ``orchid_continuum.brain_connectors`` entry-point group.
    Discovery never executes a connector action.
    """

    def __init__(self) -> None:
        self._connectors: dict[str, BrainConnector] = {}

    def register(self, connector: BrainConnector) -> None:
        connector_id = connector.id.strip()
        if not connector_id or not connector.version.strip():
            raise ValueError("INVALID_CONNECTOR_IDENTITY")
        if connector_id in self._connectors:
            raise ValueError("CONNECTOR_ALREADY_REGISTERED")
        self._connectors[connector_id] = connector

    def discover(self) -> list[str]:
        discovered: list[str] = []
        selected = entry_points()
        selected = (
            selected.select(group="orchid_continuum.brain_connectors")
            if hasattr(selected, "select")
            else selected.get("orchid_continuum.brain_connectors", [])
        )
        for entry_point in selected:
            loaded = entry_point.load()
            connector = loaded() if callable(loaded) else loaded
            self.register(connector)
            discovered.append(connector.id)
        return sorted(discovered)

    def get(self, connector_id: str) -> BrainConnector:
        try:
            return self._connectors[connector_id]
        except KeyError as exc:
            raise LookupError("CONNECTOR_NOT_FOUND") from exc

    def catalog(self) -> list[dict[str, Any]]:
        return [
            {
                "id": item.id,
                "name": item.name,
                "version": item.version,
                "capabilities": list(item.capabilities),
                "health": item.health(),
            }
            for item in sorted(self._connectors.values(), key=lambda value: value.id)
        ]


@dataclass(frozen=True)
class ManifestConnector:
    """Non-secret metadata connector declaration.

    A manifest advertises a supported integration without making network calls.
    Production adapters replace it through the registry entry-point contract.
    """

    id: str
    name: str
    version: str
    capabilities: tuple[str, ...]
    metadata_only: bool = True

    def execute(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        if action != "describe":
            raise RuntimeError("CONNECTOR_ADAPTER_NOT_CONFIGURED")
        return {
            "connector_id": self.id,
            "metadata_only": self.metadata_only,
            "capabilities": list(self.capabilities),
        }

    def health(self) -> dict[str, Any]:
        return {
            "status": "declared",
            "operational": False,
            "metadata_only": self.metadata_only,
        }


LITERATURE_CONNECTORS = (
    ManifestConnector("crossref", "Crossref", "1.0", ("doi", "authors", "citations")),
    ManifestConnector(
        "openalex", "OpenAlex", "1.0", ("works", "authors", "concepts", "citations")
    ),
    ManifestConnector(
        "semantic-scholar",
        "Semantic Scholar",
        "1.0",
        ("papers", "authors", "citations"),
    ),
    ManifestConnector("pubmed", "PubMed", "1.0", ("papers", "authors", "abstracts")),
    ManifestConnector("gbif", "GBIF", "1.0", ("occurrences", "taxonomy", "geography")),
    ManifestConnector(
        "bhl",
        "Biodiversity Heritage Library",
        "1.0",
        ("literature", "pages", "taxonomy"),
    ),
    ManifestConnector("jstor", "JSTOR", "1.0", ("metadata",), metadata_only=True),
)


def default_registry() -> ConnectorRegistry:
    registry = ConnectorRegistry()
    for connector in LITERATURE_CONNECTORS:
        registry.register(connector)
    registry.discover()
    return registry
