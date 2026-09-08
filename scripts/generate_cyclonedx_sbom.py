#!/usr/bin/env python3
"""Generate a deterministic CycloneDX inventory from the installed environment."""
from __future__ import annotations
import hashlib
import importlib.metadata
import json
from pathlib import Path

components = []
for dist in sorted(importlib.metadata.distributions(), key=lambda d: (d.metadata["Name"] or "").lower()):
    name = dist.metadata["Name"]
    version = dist.version
    if not name:
        continue
    components.append({
        "type": "library",
        "name": name,
        "version": version,
        "purl": f"pkg:pypi/{name.lower().replace('_', '-')}@{version}",
    })

document = {
    "bomFormat": "CycloneDX",
    "specVersion": "1.5",
    "serialNumber": "urn:uuid:00000000-0000-0000-0000-000000000000",
    "version": 1,
    "metadata": {"component": {"type": "application", "name": "orchid-calyx-backend"}},
    "components": components,
}
payload = json.dumps(document, indent=2, sort_keys=True) + "\n"
Path("artifacts").mkdir(exist_ok=True)
Path("artifacts/orchid-calyx-backend.cdx.json").write_text(payload, encoding="utf-8")
digest = hashlib.sha256(payload.encode()).hexdigest()
Path("artifacts/orchid-calyx-backend.cdx.json.sha256").write_text(
    f"{digest}  orchid-calyx-backend.cdx.json\n", encoding="utf-8"
)
print(f"Recorded {len(components)} installed direct and transitive components")
