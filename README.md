# Calyx - Orchid Show Management System

Backend API for Calyx, powered by Orchid Continuum.

## Run Command

For Replit Deployments:
```bash
uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-3000}
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | No | `sqlite:///./calyx.db` | PostgreSQL connection string for production |
| `PORT` | No | `3000` | Port to bind (set by Replit in deployments) |
| `CORS_ALLOW_ORIGINS` | No | `*` | Comma-separated allowed origins, or `*` for all |
| `CALYX_API_KEY` | No | None | If set, requires `X-API-Key` header for `/api/*` routes |
| `AUTO_CREATE_TABLES` | No | `1` | Set to `0` to disable auto table creation |

## API Endpoints

### Health
```bash
curl https://your-app.replit.app/health
# {"status":"ok"}
```

### Tile Registry
```bash
curl https://your-app.replit.app/api/tiles/registry
```

**Response Schema:**
```json
{
  "version": "1.0",
  "tiles": [
    {
      "id": "string",
      "title": "string",
      "route": "string",
      "role_visibility": ["admin", "exhibitor", "volunteer", "judge"],
      "status": "active"
    }
  ]
}
```

### Shows CRUD
```bash
# List shows
curl https://your-app.replit.app/api/shows

# Create show
curl -X POST https://your-app.replit.app/api/shows \
  -H "Content-Type: application/json" \
  -d '{"name": "Spring Show 2026", "start_date": "2026-03-15", "location": "Garden Center"}'

# Get show
curl https://your-app.replit.app/api/shows/{show_id}

# Update show
curl -X PATCH https://your-app.replit.app/api/shows/{show_id} \
  -H "Content-Type: application/json" \
  -d '{"location": "New Location"}'

# Delete show
curl -X DELETE https://your-app.replit.app/api/shows/{show_id}
```

### Entries CRUD
```bash
# List entries (optionally filter by show_id)
curl https://your-app.replit.app/api/entries?show_id={show_id}

# Create entry
curl -X POST https://your-app.replit.app/api/entries \
  -H "Content-Type: application/json" \
  -d '{"show_id": "...", "exhibitor_name": "John Doe", "plant_name": "Cattleya", "class_code": "A1"}'
```

### Volunteer Tasks CRUD
```bash
# List tasks
curl https://your-app.replit.app/api/volunteer-tasks?show_id={show_id}

# Create task
curl -X POST https://your-app.replit.app/api/volunteer-tasks \
  -H "Content-Type: application/json" \
  -d '{"show_id": "...", "title": "Setup tables", "assigned_to": "Jane"}'
```

### Awards CRUD
```bash
# List awards
curl https://your-app.replit.app/api/awards?entry_id={entry_id}

# Create award
curl -X POST https://your-app.replit.app/api/awards \
  -H "Content-Type: application/json" \
  -d '{"entry_id": "...", "award_name": "Best in Show", "level": "1st"}'
```

## With API Key Authentication

If `CALYX_API_KEY` is set:
```bash
curl https://your-app.replit.app/api/shows \
  -H "X-API-Key: your-api-key-here"
```

## Interactive Docs

Visit `/docs` for Swagger UI documentation.
