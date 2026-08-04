import hashlib
import json


def build_artifact_bundle(*, run_id: str, commit_sha: str, lane_results: dict) -> dict:
    blockers: list[str] = []
    if not run_id:
        blockers.append("RUN_ID_MISSING")
    if len(commit_sha) < 7:
        blockers.append("COMMIT_SHA_INVALID")
    if not lane_results:
        blockers.append("LANE_RESULTS_MISSING")
    failed = sorted(name for name, result in lane_results.items() if result.get("certified") is not True)
    blockers.extend(f"{name}:NOT_CERTIFIED" for name in failed)
    payload = {"run_id": run_id, "commit_sha": commit_sha, "lane_results": lane_results}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return {
        **payload,
        "artifact_hash": hashlib.sha256(canonical.encode()).hexdigest(),
        "complete": not blockers,
        "blockers": blockers,
        "production_action_authorized": False,
    }
