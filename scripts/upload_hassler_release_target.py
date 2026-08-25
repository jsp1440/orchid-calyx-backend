"""Run the guarded Hassler uploader against a manifest-selected exact release.

The existing uploader keeps all production-write safeguards: dry-run by default,
explicit ``--execute``, exact confirmation token, byte-size/SHA validation,
durable readback, and no staging/activation/graph authority. This adapter only
supplies the release identity from the validated manifest so a new Hassler update
does not require editing application code.
"""

from __future__ import annotations

from runtime.hassler_release_target import load_hassler_release_target
from scripts import upload_hassler_release_guarded as uploader


def apply_release_target() -> dict[str, object]:
    target = load_hassler_release_target()
    uploader.EXPECTED_FILENAME = target.filename
    uploader.EXPECTED_SIZE_BYTES = target.size_bytes
    uploader.EXPECTED_SHA256 = target.sha256
    uploader.VERSION_LABEL = target.version_label
    uploader.ACQUIRED_AT = target.acquired_at
    uploader.EXECUTION_CONFIRMATION = target.execution_confirmation
    return target.as_dict()


def main() -> int:
    apply_release_target()
    return uploader.main()


if __name__ == "__main__":
    raise SystemExit(main())
