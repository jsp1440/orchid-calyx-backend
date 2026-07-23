"""Kernel exception hierarchy."""


class KernelError(Exception):
    """Base exception for Scientific Kernel failures."""


class InvalidOCIDError(KernelError, ValueError):
    """Raised when an OCID cannot be parsed or validated."""


class ScientificObjectValidationError(KernelError, ValueError):
    """Raised when a scientific object violates a kernel contract."""
