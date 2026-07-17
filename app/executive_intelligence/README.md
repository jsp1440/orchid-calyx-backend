# Executive Intelligence API

- `POST /api/executive-intelligence/sources/{source_id}/recommendations`
- `GET /api/executive-intelligence/recommendations`
- `PATCH /api/executive-intelligence/recommendations/{recommendation_id}`
- `POST /api/executive-intelligence/providers/route`

All endpoints require the existing owner session or API key. Recommendation generation is permitted only for APPROVED or PUBLISHED intake sources.
