class PublicationError(RuntimeError):
    """Fail-closed controlled-publication error with a stable reason code."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class TrustedInputError(PublicationError):
    pass


class PolicyError(PublicationError):
    pass


class LifecycleError(PublicationError):
    pass
