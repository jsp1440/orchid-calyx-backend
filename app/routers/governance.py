from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db

router = APIRouter(prefix="/governance", tags=["Governance"])


@router.get("/health")
def governance_health(db: Session = Depends(get_db)):
    checks = {
        "tracker_log": {"status": "unknown"},
        "operating_policies": {"status": "unknown"},
    }

    try:
        tracker_count = (
            db.execute(text("SELECT COUNT(*) FROM oc_governance.tracker_log")).scalar()
            or 0
        )
        checks["tracker_log"] = {
            "status": "ok",
            "row_count": tracker_count,
        }
    except Exception as e:
        checks["tracker_log"] = {
            "status": "error",
            "detail": str(e),
        }

    try:
        policy_count = (
            db.execute(
                text("SELECT COUNT(*) FROM oc_governance.operating_policies")
            ).scalar()
            or 0
        )
        checks["operating_policies"] = {
            "status": "ok",
            "row_count": policy_count,
        }
    except Exception as e:
        checks["operating_policies"] = {
            "status": "error",
            "detail": str(e),
        }

    overall = "ok"
    for value in checks.values():
        if value.get("status") == "error":
            overall = "degraded"
            break

    return {
        "status": overall,
        "checks": checks,
    }


@router.get("/tracker")
def get_tracker(db: Session = Depends(get_db)):
    rows = (
        db.execute(
            text(
                """
                SELECT id, phase, component, status, details, created_at
                FROM oc_governance.tracker_log
                ORDER BY created_at DESC
                LIMIT 100
                """
            )
        )
        .mappings()
        .all()
    )

    return {
        "status": "ok",
        "count": len(rows),
        "items": [dict(r) for r in rows],
    }


@router.get("/policies")
def get_policies(db: Session = Depends(get_db)):
    rows = (
        db.execute(
            text(
                """
                SELECT policy_key, version, title, status, created_at
                FROM oc_governance.operating_policies
                ORDER BY created_at DESC
                """
            )
        )
        .mappings()
        .all()
    )

    return {
        "status": "ok",
        "count": len(rows),
        "items": [dict(r) for r in rows],
    }


@router.get("/dashboard")
def get_dashboard(db: Session = Depends(get_db)):
    summary = {
        "tracker_entries": 0,
        "policies": 0,
        "latest_tracker": None,
        "latest_policy": None,
    }

    try:
        summary["tracker_entries"] = (
            db.execute(text("SELECT COUNT(*) FROM oc_governance.tracker_log")).scalar()
            or 0
        )
    except Exception:
        summary["tracker_entries"] = 0

    try:
        summary["policies"] = (
            db.execute(
                text("SELECT COUNT(*) FROM oc_governance.operating_policies")
            ).scalar()
            or 0
        )
    except Exception:
        summary["policies"] = 0

    try:
        latest_tracker = (
            db.execute(
                text(
                    """
                    SELECT id, phase, component, status, details, created_at
                    FROM oc_governance.tracker_log
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                )
            )
            .mappings()
            .first()
        )
        summary["latest_tracker"] = dict(latest_tracker) if latest_tracker else None
    except Exception:
        summary["latest_tracker"] = None

    try:
        latest_policy = (
            db.execute(
                text(
                    """
                    SELECT policy_key, version, title, status, created_at
                    FROM oc_governance.operating_policies
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                )
            )
            .mappings()
            .first()
        )
        summary["latest_policy"] = dict(latest_policy) if latest_policy else None
    except Exception:
        summary["latest_policy"] = None

    return {
        "status": "ok",
        "summary": summary,
    }
