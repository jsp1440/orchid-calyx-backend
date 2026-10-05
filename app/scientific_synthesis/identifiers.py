"""One citation identity rule for every scientific-synthesis comparison.

A DOI is the only identifier two modules can compare to decide that a paper and
a bibliographic record are the same work. Each module used to carry its own
copy of the normalisation, and the copies disagreed: discovery stripped the
``dx.doi.org`` resolver form and ``doi:`` followed by spaces, the evidence
matrix did neither. A paper whose DOI identifier arrived as
``https://dx.doi.org/10.…`` therefore failed to match its own bibliographic
record in the matrix, and the build refused with
``BIBLIOGRAPHIC_PAPER_IDENTITY_UNPROVEN``.

The rule is deliberately lenient about *form* and says nothing about *validity*:
it never invents or repairs a DOI, and an empty or whitespace-only value is
"no DOI" (``None``), never a match. Callers that must reject a malformed DOI
(for example the intake validator) layer their own check on top of it.
"""

from __future__ import annotations

import re

_RESOLVER_PREFIX = re.compile(r"^https?://(?:dx\.)?doi\.org/")
_SCHEME_PREFIX = re.compile(r"^doi:\s*")


def normalize_doi(value: str | None) -> str | None:
    """Return the canonical comparison form of a DOI, or ``None`` if there is none."""
    if not value:
        return None
    normalized = value.strip().lower()
    # Strip repeatedly so a resolver URL that wraps a ``doi:`` form still reduces
    # to the bare DOI regardless of which prefix came first.
    previous = None
    while previous != normalized:
        previous = normalized
        normalized = _RESOLVER_PREFIX.sub("", normalized, count=1).strip()
        normalized = _SCHEME_PREFIX.sub("", normalized, count=1).strip()
    return normalized or None
