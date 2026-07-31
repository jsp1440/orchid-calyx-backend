from __future__ import annotations

import csv
import io
import json
from typing import Any

try:
    import yaml
except ImportError:  # optional dependency
    yaml = None


def parse_structured(content: str, suffix: str) -> Any:
    suffix = suffix.lower()
    if suffix == ".json":
        return json.loads(content)
    if suffix in {".yaml", ".yml"}:
        if yaml is None:
            raise RuntimeError("PyYAML is required for YAML parsing")
        return yaml.safe_load(content)
    if suffix == ".csv":
        return list(csv.DictReader(io.StringIO(content)))
    raise ValueError(f"unsupported structured format: {suffix}")
