# CALYX-639D — Exact-Head Validation

**Branch head validated:** `2931eb8deb085383a2d01d4adc73af14b1f08e86`  
**Draft PR:** #640  
**GitHub Actions run:** 31270468655  
**Result:** PASS

The dedicated `CALYX-639 Propagation Intelligence` workflow executed against the exact branch head and completed successfully.

Successful job: `propagation-contract`.

Successful validation steps:

1. repository checkout;
2. Python 3.12 setup;
3. focused dependency installation;
4. compilation of:
   - `runtime/recalcitrant_orchid_propagation.py`
   - `runtime/propagation_research_dataset.py`
   - `runtime/terrestrial_orchid_propagation_comparators.py`
   - `runtime/propagation_comparator_dataset.py`
   - `runtime/router_fastapi.py`;
5. execution of all five focused CALYX-639 test files:
   - `tests/test_recalcitrant_orchid_propagation.py`
   - `tests/test_recalcitrant_orchid_propagation_api.py`
   - `tests/test_propagation_research_dataset.py`
   - `tests/test_terrestrial_orchid_propagation_comparators.py`
   - `tests/test_propagation_comparator_dataset.py`.

The repository `CALYX Workflow Governance Audit` also completed successfully for the same head context.

This validation removes the prior exact-head CI infrastructure blocker. It does **not** authorize merge, deployment, scientific publication, destructive experimentation, or canonical Knowledge Graph mutation.

Remaining blockers are scientific/dependency blockers rather than focused implementation-test failures:

- authorized full Davis et al. Methods/full-text extraction;
- closer *Thelymitra*/Diurideae geophytic comparator evidence;
- CALYX-631 immutable row transport before claiming Research Station row persistence;
- human scientific review before experimental protocol selection.
