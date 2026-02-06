"""
tools/introspect_api.py

Purpose:
- Inspect the FastAPI app in your repo and list routes.
- Highlight routes that look like judging/awards/volunteers.
- Export OpenAPI spec to tools/openapi.json for quick checking.

Run:
  python tools/introspect_api.py
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List, Tuple


def _load_app():
    """
    Adjust import paths here if your FastAPI app is created elsewhere.
    This repo (per your screenshots) likely has app/main.py with a FastAPI instance named `app`.
    """
    # Ensure repo root is on path
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    sys.path.insert(0, repo_root)

    try:
        # Most common: app/main.py -> app = FastAPI(...)
        from app.main import app  # type: ignore
        return app
    except Exception as e1:
        # Fallbacks you might have (adjust if needed)
        try:
            from main import app  # type: ignore
            return app
        except Exception as e2:
            raise RuntimeError(
                "Could not import FastAPI app. Tried: `from app.main import app` and `from main import app`.\n"
                f"Error 1: {e1}\nError 2: {e2}\n"
                "Fix: edit _load_app() import to match where your FastAPI instance lives."
            )


def _route_info(route) -> Tuple[str, List[str], str]:
    path = getattr(route, "path", "")
    methods = sorted(list(getattr(route, "methods", []) or []))
    name = getattr(route, "name", "") or ""
    return path, methods, name


def main() -> None:
    app = _load_app()

    routes = []
    for r in app.routes:
        path, methods, name = _route_info(r)
        # Skip Starlette internal routes without methods/path
        if not path or not methods:
            continue
        routes.append((path, methods, name))

    # Sort for readability
    routes.sort(key=lambda x: (x[0], ",".join(x[1])))

    keywords = [
        "judge", "judg", "award", "score", "aos", "entry", "volunteer",
        "shift", "checkin", "show"
    ]

    def is_interesting(path: str) -> bool:
        p = path.lower()
        return any(k in p for k in keywords)

    print("\n=== ALL ROUTES (sorted) ===")
    for path, methods, name in routes:
        print(f"{','.join(methods):12s} {path:45s}  ({name})")

    print("\n=== HIGHLIGHTS (judging/awards/volunteers/shows/etc) ===")
    for path, methods, name in routes:
        if is_interesting(path):
            print(f"{','.join(methods):12s} {path:45s}  ({name})")

    # Export OpenAPI if available
    try:
        spec: Dict[str, Any] = app.openapi()
        out_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "openapi.json"))
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(spec, f, indent=2)
        print(f"\n✅ OpenAPI exported to: {out_path}")
        print(
            "   Tip: open that file in Replit and search for 'judg', 'award', 'volunteer'."
        )
    except Exception as e:
        print(f"\n⚠️ Could not export OpenAPI: {e}")


if __name__ == "__main__":
    main()
