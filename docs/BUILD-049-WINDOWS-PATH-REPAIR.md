# BUILD-049 Windows Path Repair Audit

## Summary

During BUILD-049, a Windows checkout of `jsp1440/orchid-calyx-backend` could not safely commit because current `main` tracks paths that Windows cannot materialize. The BUILD-049 backend implementation was therefore recovered through GitHub remote writes rather than through the damaged Windows worktree.

No malformed-path deletion is included in BUILD-049. A separate sanitation PR is not required before BUILD-049 because the GitHub contents API can add and update the intended files without touching invalid paths. A future repository hygiene PR should still remove or rename the malformed artifacts after owner review.

## Invalid Tracked Paths

### `alth.py, `

- Blob SHA: `8d25a0863a244c71de327b0ce5901977ab4fcaff`
- Introduced/observed commit: `f5f01a916ce41e7ac927c9592829e5c636d14bbb` (`Saved progress at the end of the loop`, 2026-03-14)
- Content: duplicate FastAPI health router with `GET /health` and `GET /system/status`.
- Reference audit: repository search found no imports of `alth`; preservation docs already classify it as `ORPHANED — duplicate health router, comma in filename`.
- Disposition: accidental malformed duplicate artifact. Safe candidate for removal in a dedicated sanitation PR after confirming no deployment script references it.

### Giant JSX literal filename beginning `import React from "react"; export default function App() ...`

- Blob SHA: `e69de29bb2d1d6434b8b29ae775ad8c2e48c5391`
- Relevant commits found by object search: `8f1fea95ac7b36810e88e6ab6057558f7e58f40a`, `729519c5c164849243f140a4639f06c13fa706a2`, `5b228a748e1e27c1440fc83f977bb77988685335`, `f84a9d6121321e25c6851f6357b51dc90da47488`, `f5f01a916ce41e7ac927c9592829e5c636d14bbb`.
- Content: empty blob.
- Reference audit: no meaningful source reference; the filename itself appears to be accidental generated React demo content.
- Disposition: accidental malformed empty artifact. Safe candidate for removal in a dedicated sanitation PR.

## Why BUILD-049 Did Not Repair These Paths

BUILD-049 is a harvester control-plane build. Repairing malformed historical root paths is repository sanitation work and should remain narrowly scoped. The backend BUILD-049 branch was populated through remote-safe GitHub writes, so no invalid-path deletion was necessary to deliver the feature branch.

## Future Sanitation PR Scope

Recommended branch: `repair/windows-invalid-tracked-paths`.

Minimal changes:

1. Remove `alth.py, ` after preserving its duplicate content in this audit record.
2. Remove the empty JSX-literal filename.
3. Include this audit file or a follow-up sanitation note.
4. Confirm no app imports, startup commands, deployment scripts, or tests reference either path.
5. Run route/import validation from a Linux or remote-safe checkout.

Do not combine sanitation with feature work.
