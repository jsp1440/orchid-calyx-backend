# BUILD-618 scope examples

## Bounded physiological claim

```json
{
  "scope_class": "bounded",
  "taxa": ["Phalaenopsis"],
  "tissues": ["young leaf"],
  "developmental_stages": ["expansion"],
  "treatments": {"wavelength_nm": 450}
}
```

## Bounded cultivation observation

```json
{
  "scope_class": "bounded",
  "taxa": ["Dendrobium cuthbertsonii"],
  "organs": ["root"],
  "cultivation_context": {
    "location": "greenhouse",
    "night_temperature_c": 16,
    "relative_humidity_percent": 80
  }
}
```

## Global assertion

A global scope is allowed only when the scientific evidence supports a genuinely general claim and `global_justification` explains that basis. It is never inferred merely because a source omitted context.
