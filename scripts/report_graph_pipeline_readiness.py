"""Print the read-only graph-pipeline readiness contract as JSON."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from runtime.graph_pipeline_readiness import build_graph_pipeline_readiness


if __name__ == "__main__":
    print(json.dumps(build_graph_pipeline_readiness(), indent=2, sort_keys=True))
