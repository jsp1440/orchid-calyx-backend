"""Abstract interface for all connectors.

Every connector must implement this interface to be discovered and executed
by the ConnectorRegistry. This enables the plugin-based architecture that
allows new connectors to be added without modifying the core runtime.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ConnectorInterface(ABC):
    """Abstract base class for all connectors.

    Connectors must implement:
    - name: The human-readable connector name
    - health(): Check connector health status
    - execute(task): Execute a task through the connector
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the connector name (e.g., 'github', 'gmail', 'openai')."""

    @abstractmethod
    def health(self) -> dict[str, Any]:
        """Return connector health status.

        Returns:
            dict with keys:
            - 'status': 'healthy' or 'unhealthy'
            - 'timestamp': ISO 8601 timestamp
            - 'error' (optional): Error message if unhealthy
        """

    @abstractmethod
    def execute(self, task: str, **kwargs) -> dict[str, Any]:
        """Execute a task through the connector.

        Args:
            task: Task identifier (e.g., 'status', 'list', 'sync')
            **kwargs: Task-specific parameters

        Returns:
            dict with execution result, including:
            - 'status': 'success' or 'failure'
            - 'task': The task executed
            - 'result': The task result (if successful)
            - 'error' (optional): Error message (if failed)
            - 'execution_time_ms': Execution time in milliseconds
        """
