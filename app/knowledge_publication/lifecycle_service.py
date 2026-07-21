class PublicationLifecycleService:
    """Internal reference-only facade; authoritative state is repository-loaded."""

    def __init__(self, repository):
        self.repository = repository

    def supersede(
        self, predecessor_id, successor_id, authority, reason, correction_record_id=None
    ):
        return self.repository.supersede(
            predecessor_id, successor_id, authority, reason, correction_record_id
        )

    def withdraw(self, publication_id, authority, reason):
        return self.repository.withdraw(publication_id, authority, reason)

    def retract(self, publication_id, authority, reason, invalidation_source):
        return self.repository.retract(
            publication_id, authority, reason, invalidation_source
        )

    def restore(self, publication_id, authority, reason):
        return self.repository.restore(publication_id, authority, reason)

    def require_reevaluation(
        self, publication_id, authority, reason, trigger_reference, batch_size=100
    ):
        return self.repository.require_reevaluation(
            publication_id, authority, reason, trigger_reference, batch_size
        )

    def prepare_rollback(self, publication_id, authority, reason, detection_source):
        return self.repository.prepare_rollback(
            publication_id, authority, reason, detection_source
        )

    def execute_rollback(self, rollback_id, authority):
        return self.repository.execute_rollback(rollback_id, authority)
