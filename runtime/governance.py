from __future__ import annotations
from .models import GovernanceReview


class GovernanceService:
    """Constitution-aware autonomy gate for Calyx Runtime."""

    HARD_STOP_ACTIONS = {
        "merge_to_main",
        "delete_data",
        "send_email",
        "publish_scientific_claim",
        "database_schema_change",
        "change_permissions",
        "modify_autonomy_policy",
    }

    def review_action(self, action: str, requested_level: int = 1) -> GovernanceReview:
        reasons = ["Constitution check required for all runtime actions."]

        if action in self.HARD_STOP_ACTIONS:
            return GovernanceReview(
                allowed=False,
                autonomy_level=5,
                requires_human_approval=True,
                reasons=reasons + [f"Action '{action}' requires human approval."],
            )

        if requested_level >= 5:
            return GovernanceReview(
                allowed=False,
                autonomy_level=requested_level,
                requires_human_approval=True,
                reasons=reasons + ["Production-level action requires human approval."],
            )

        return GovernanceReview(
            allowed=True,
            autonomy_level=requested_level,
            requires_human_approval=False,
            reasons=reasons + ["Action is within current permitted runtime scope."],
        )
