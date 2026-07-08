# BUILD-039A deployment checklist

1. Merge BUILD-039A.
2. Redeploy `orchid-calyx-backend` on Render.
3. Open Mission Control from `https://orchid-continuum-frontend-vof6.onrender.com`.
4. Confirm `/api/mission-control/*` cards no longer report browser CORS/load failures.
5. If fallback remains, inspect frontend payload mapping and endpoint response shapes next.
