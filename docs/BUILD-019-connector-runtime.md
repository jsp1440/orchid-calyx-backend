# BUILD-019 — Connector Runtime Scaffolds

BUILD-019 converts BUILD-018 connector plans into review-ready scaffold records.

## Purpose

BUILD-018 identifies that Brain data exists but runtime connector wiring is missing or thin. BUILD-019 prepares deterministic adapter scaffolds so each connector can be promoted into a concrete runtime module in the next implementation step.

## Added

- `runtime/connector_runtime.py`
- File-backed output under `runtime/connector_runs/`
- Scaffold records with adapter name, module path, endpoint prefix, validation contract, connector targets, and next actions

## Behavior

The builder reads BUILD-018 connector plans and creates one scaffold record per plan. It does not mutate Brain data or call external APIs. It is safe to run on Render without new infrastructure.

## Acceptance check

A BUILD-019 output should report:

- `build: BUILD-019`
- `status: connector_scaffolds_ready`
- one scaffold per BUILD-018 plan
- adapter names and module paths for Taxonomy, Images, Occurrences, Pollination, Mycorrhiza, and other planned domains

## Next build

BUILD-020 should turn these scaffold records into first-class connector adapters and public runtime connector endpoints.
