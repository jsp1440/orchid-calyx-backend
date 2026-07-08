# BUILD-039A PR body source

Summary:
- Adds scoped CORS response headers for read-only Mission Control telemetry routes.
- Adds OPTIONS support for `/api/mission-control/{full_path:path}`.
- Does not enable write controls.

Deploy:
- Backend redeploy required after merge.
- Frontend redeploy not required.
