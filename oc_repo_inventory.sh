#!/usr/bin/env bash
set -euo pipefail

OUT="OC_REPO_INVENTORY_$(date -u +%Y%m%dT%H%M%SZ).txt"

say () { printf "%s\n" "$*" | tee -a "$OUT" >/dev/null; }

say "============================================================"
say "ORCHID CONTINUUM — REPO INVENTORY"
say "UTC: $(date -u)"
say "PWD: $(pwd)"
say "============================================================"
say ""

# Basic git metadata
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  say "[GIT]"
  say "Repo root: $(git rev-parse --show-toplevel)"
  say "Branch:    $(git rev-parse --abbrev-ref HEAD)"
  say "Commit:    $(git rev-parse HEAD)"
  say "Last:      $(git log -1 --pretty=format:'%ci | %an | %s')"
  say "Remotes:"
  git remote -v | tee -a "$OUT" >/dev/null || true
  say ""
else
  say "[GIT] Not a git repo here."
  say ""
fi

# Top-level structure
say "[TOP LEVEL]"
ls -la | tee -a "$OUT" >/dev/null || true
say ""

# Common “what is this?” markers
say "[KEY FILES FOUND]"
for f in README.md readme.md package.json pyproject.toml requirements.txt requirements*.txt Dockerfile docker-compose.yml Render.yaml render.yaml .env .replit; do
  if [ -e "$f" ]; then say "FOUND: $f"; fi
done
say ""

# Entry points / likely run targets
say "[LIKELY ENTRYPOINTS]"
find . -maxdepth 3 -type f \( \
  -name "main.py" -o -name "app.py" -o -name "server.py" -o -name "run*.py" -o \
  -name "index.ts" -o -name "index.tsx" -o -name "main.ts" -o -name "main.tsx" -o \
  -name "worker*.py" -o -name "wsgi.py" -o -name "asgi.py" \
\) 2>/dev/null | sed 's|^\./||' | sort | tee -a "$OUT" >/dev/null || true
say ""

# “Philosophy quiz” / quiz signals
say "[QUIZ / PHILOSOPHY SIGNALS]"
( rg -n --no-heading --hidden --glob='!.git/*' "(philosophy quiz|orchid philosophy|quiz)" . 2>/dev/null || true ) | head -n 200 | tee -a "$OUT" >/dev/null
say ""

# FastAPI / Flask / Next / etc quick signals
say "[STACK SIGNALS]"
( rg -n --no-heading --hidden --glob='!.git/*' "(fastapi|uvicorn|flask|django|nextjs|react|vite|express)" . 2>/dev/null || true ) | head -n 200 | tee -a "$OUT" >/dev/null
say ""

say "============================================================"
say "DONE. Report: $OUT"
say "============================================================"
