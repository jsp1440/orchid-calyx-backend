from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.architecture import BrainArchitect  # noqa: E402


def main() -> None:
    result = BrainArchitect(ROOT).run(write=True)
    print(
        "BUILD-080 architecture generation complete: "
        f"documents={len(result.documents)} "
        f"domains={len(result.ontology)} "
        f"dependencies={len(result.dependencies)} "
        f"gaps={len(result.gaps)}"
    )


if __name__ == "__main__":
    main()
