# PR review notes

Review order:

1. `app/executive_intelligence/engine.py`
2. `migrations/074_unified_executive_intelligence.sql`
3. `app/executive_intelligence/repository.py`
4. `app/executive_intelligence/routes.py`
5. `tests/test_build_074_executive_intelligence.py`
6. `app/routers/health.py`

The migration is additive and must not be applied automatically before CI and independent review.
