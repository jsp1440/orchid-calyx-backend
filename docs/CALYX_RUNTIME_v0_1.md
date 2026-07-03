# Calyx Runtime v0.1 — Heartbeat

This is the first production-code scaffold for **Active Calyx**.

Runtime loop:

```text
Observe → Diagnose → Plan → Govern → Report → Remember
```

## Endpoints

After router registration:

```text
/api/runtime/heartbeat
/api/runtime/health
```

## Environment variables

Optional:

- `CALYX_BACKEND_URL`
- `CALYX_FRONTEND_URL`
- `DATABASE_URL`

## Safety

This version does not merge code, delete files, alter schemas, send emails, or publish scientific claims.

It writes only a local runtime journal event through `RuntimeMemoryWriter`. Production memory writes should later go to approved Engineering Memory tables.
