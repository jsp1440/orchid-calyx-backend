# BUILD-085 — Brain Import Operational Launch and Live Validation

BUILD-085 operationalizes the existing BUILD-082/083/084 pipeline without replacing any import, hashing, provenance, revision, classification, extraction, review, or Mission Control logic.

## Required environment variables

- `DATABASE_URL`
- `GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON`
- `GOOGLE_DRIVE_BRAIN_SOURCE_ID`
- `GOOGLE_DRIVE_BRAIN_ROOT_FOLDER_ID`
- `BRAIN_IMPORT_ACTOR` (optional; defaults to `owner_session`)

## Operator commands

### Preview bulk import

```bash
python3 scripts/build_085_operational_launch_validation.py preview --source-id "$GOOGLE_DRIVE_BRAIN_SOURCE_ID"
```

### Execute bulk import

```bash
python3 scripts/build_085_operational_launch_validation.py execute --run-id <bulk_run_id>
```

### Resume bulk import

```bash
python3 scripts/build_085_operational_launch_validation.py resume --run-id <bulk_run_id>
```

### Cancel bulk import

```bash
python3 scripts/build_085_operational_launch_validation.py cancel --run-id <bulk_run_id>
```

### Inspect status/history

```bash
python3 scripts/build_085_operational_launch_validation.py status --run-id <bulk_run_id>
python3 scripts/build_085_operational_launch_validation.py final-report --source-id "$GOOGLE_DRIVE_BRAIN_SOURCE_ID" --root-folder-id "$GOOGLE_DRIVE_BRAIN_ROOT_FOLDER_ID"
```

### View the final report

```bash
python3 scripts/build_085_operational_launch_validation.py final-report --source-id "$GOOGLE_DRIVE_BRAIN_SOURCE_ID" --root-folder-id "$GOOGLE_DRIVE_BRAIN_ROOT_FOLDER_ID"
```

The script prints JSON output with either:

- `READY — CONTROLLED BRAIN IMPORT VALIDATED`
- `NOT READY` with the exact blocking reason
