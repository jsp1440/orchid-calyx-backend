from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AuditContext:
    actor: str
    correlation_id: str
    reason_code: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if (
            not self.actor.strip()
            or not self.correlation_id.strip()
            or not self.reason_code.strip()
        ):
            raise ValueError("INCOMPLETE_AUDIT_CONTEXT")
