"""Run the existing read-only Hassler discovery against a manifest-selected release.

This adapter removes the need to edit Python when Hassler publishes a new
WorldOrchids file. Set ``CALYX_HASSLER_RELEASE_MANIFEST`` to a strictly validated
manifest and run this script. The underlying discovery remains GET-only apart
from owner-session authentication and grants no mutation authority.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = str(Path(__file__).resolve().parents[1])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from runtime.hassler_release_target import load_hassler_release_target  # noqa: E402
from scripts import discover_hassler_release_intake as discovery  # noqa: E402


def apply_release_target() -> dict[str, object]:
    target = load_hassler_release_target()
    discovery.EXPECTED_FILENAME = target.filename
    discovery.EXPECTED_SHA256 = target.sha256
    return target.as_dict()


def main() -> int:
    apply_release_target()
    return discovery.main()


if __name__ == "__main__":
    raise SystemExit(main())
