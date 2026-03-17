#!/usr/bin/env bash
set -e

OUT="governance_backend_audit.txt"
: > "$OUT"

{
  echo "===== app/main.py (first 160 lines) ====="
  if [ -f app/main.py ]; then
    sed -n '1,160p' app/main.py
  else
    echo "app/main.py not found"
  fi

  echo
  echo "===== app/routers files ====="
  if [ -d app/routers ]; then
    find app/routers -maxdepth 1 -type f | sort
  else
    echo "app/routers directory not found"
  fi

  echo
  echo "===== router registration / db wiring grep ====="
  grep -RIn \
    -e 'include_router' \
    -e 'APIRouter' \
    -e 'get_db' \
    -e 'SessionLocal' \
    -e 'create_engine' \
    -e 'DATABASE_URL' \
    app 2>/dev/null || true

} > "$OUT"

echo "Wrote $OUT"
wc -l "$OUT"
