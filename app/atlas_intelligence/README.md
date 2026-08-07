# Atlas Intelligence Module

This module is the governed foundation for Atlas Earth Systems, thematic cartography, reasoning, and reproducibility.

## Primary entry point

```python
from app.atlas_intelligence import build_vertical_slice

result = build_vertical_slice()
manifest = result["manifest"]
reasoning = result["reasoning"]
brain_records = result["brain_records"]
```

## Invariants

- Spatial datasets require explicit CRS, extent, source version, license, attribution, and checksum.
- Biodiversity layers require resolved taxon identity.
- Time-dependent layers require temporal coverage.
- Thematic manifests are deterministic for identical ordered inputs.
- Reasoning distinguishes observation, inference, uncertainty, and unavailable data.
- Inference requires supporting layers and confidence.
- Unsupported causal language is rejected.
- Brain records carry durable IDs, aliases, lifecycle state, relationships, provenance URI, and checksum.
- No contract in this module authorizes publication, deployment, or production graph mutation.
