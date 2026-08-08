# CALYX-639F — Proximal Bridge Validation

**Validated implementation head:** `755f4ae60f5523f243afb155449643fa61d463d2`  
**Draft PR:** #640  
**CALYX-639 workflow run:** 31276660635  
**Governance audit run:** 31276660642  
**Result:** PASS

## Validation sequence

The first CALYX-639E exact-head run failed during test collection because `tests/test_australian_diurideae_propagation_api.py` imported FastAPI `TestClient`, which requires the optional `httpx` package. The test did not perform HTTP requests, so adding `httpx` to production requirements would have increased dependency surface without implementation value.

The failure was corrected by removing the unnecessary `TestClient` and `FastAPI` imports and validating the route/endpoint contract directly.

The corrected exact-head run completed successfully.

Successful steps:

1. checkout;
2. Python 3.12 setup;
3. focused dependency installation;
4. compilation of all CALYX-639 propagation modules, including `runtime/australian_diurideae_propagation_bridge.py` and `runtime/router_fastapi.py`;
5. execution of all seven focused test files:
   - `tests/test_recalcitrant_orchid_propagation.py`
   - `tests/test_recalcitrant_orchid_propagation_api.py`
   - `tests/test_propagation_research_dataset.py`
   - `tests/test_terrestrial_orchid_propagation_comparators.py`
   - `tests/test_propagation_comparator_dataset.py`
   - `tests/test_australian_diurideae_propagation_bridge.py`
   - `tests/test_australian_diurideae_propagation_api.py`

The CALYX Workflow Governance Audit also completed successfully for the same validated implementation head.

## What is now validated

- Queen of Sheba evidence/hypothesis separation;
- Research Station dataset adapters;
- broad terrestrial comparator evidence;
- proximal Australian *Diuris longifolia* bridge;
- non-destructive inflorescence-explant precedent representation;
- Mission Control *Diuris* source/matrix/bridge endpoints;
- fail-closed prohibition on automatic *Thelymitra* explant selection, method transfer, success probability, publication authority, and canonical Knowledge Graph mutation.

## Scientific implication

The validated implementation can now represent the following bounded conclusion:

> Non-destructive somatic PLB initiation is documented in a phylogenetically proximal Australian tuberous Diurideae orchid (*Diuris longifolia*), supporting evaluation of renewable above-ground explants before destructive Queen of Sheba tuber sampling.

It cannot claim that *Thelymitra variegata* will respond to those explants or treatments.

## Remaining blockers

- authorized complete Davis et al. full text and full treatment matrix;
- direct *Thelymitra* or same-subtribe Thelymitrinae vegetative propagation evidence, if it exists;
- complete Collins & Dixon extraction into the Literature Pipeline with exact locators;
- CALYX-631 immutable row transport before claiming Research Station row persistence;
- explicit human scientific review before selecting any experimental explant or protocol;
- no merge, deployment, scientific publication, destructive sampling, or production Knowledge Graph mutation is authorized by this validation record.
