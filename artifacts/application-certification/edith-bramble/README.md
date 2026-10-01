# Edith Bramble export-9 repair packet

`export-9-repairs.patch` applies to `story-orchids-interactive 9.zip`
(`jsp1440/edith-bramble-famous-sync@b2e88c07`, sha256 `a390b803…7a90`) — the
export proven to be the live build (its build is byte-identical to the live
`index-Di4GJQ4W.js`, certification run `edith-cert-20261001T091846Z-1757d973`).

It repairs defects the certification reproduced against export 9:

| defect (certification gate) | repair |
|---|---|
| `tsc` TS2339 `import.meta.glob` / `import.meta.env` (`app_typecheck`) | add `src/vite-env.d.ts` (`/// <reference types="vite/client" />`) |
| `tsc` TS2345 `AuthModal.tsx(61)` (`app_typecheck`) | `setNotice(String(result.message))` |
| eslint `no-unused-expressions` `SanitationSpell.tsx` 44:7, 45:7; `prefer-const` `soundscape.ts` 45:7 (`app_lint`) | `if (...) ro.observe(...)`; `const semi` |
| Go Deeper tells readers "The Orchid Continuum / Calyx integration is not live" while the page's own status reads Connected and species are read live (`runtime_oc_wiring`, `journey_go_deeper_no_stale_not_live_claim`) | accurate copy: connected read-only for species; concept / pathogen / card subjects not yet served |

The lockfile (`app_lockfile_sync`) is repaired by running `npm install` in
the application after applying the patch; the hosted workflow validates
that the regenerated lockfile installs with `npm ci`.

The hosted certification workflow applies this patch to a copy of the
export and records build / lint / typecheck / lockfile results in
`repair-validation/` — evidence about the candidate repair only. The live
runtime is certified only after the repaired source is deployed by Famous.
