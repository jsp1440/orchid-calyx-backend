SIGNALS_REQUIRING_REVIEW = {
    "evidence_changed",
    "source_superseded",
    "source_withdrawn",
    "source_retracted",
    "source_hash_mismatch",
}


def evaluate_publication_monitoring(publication: dict, signals: list[dict]) -> dict:
    publication_id = str(publication.get("publication_id") or "")
    ledger_artifact_id = str(publication.get("ledger_artifact_id") or "")
    blockers: list[str] = []
    review_reasons: list[str] = []

    if not publication_id:
        blockers.append("PUBLICATION_ID_MISSING")
    if not ledger_artifact_id:
        blockers.append("LEDGER_ARTIFACT_ID_MISSING")

    for signal in signals:
        signal_type = str(signal.get("type") or "")
        if signal_type in SIGNALS_REQUIRING_REVIEW:
            review_reasons.append(signal_type)

    review_required = bool(review_reasons)
    return {
        "publication_id": publication_id or None,
        "ledger_artifact_id": ledger_artifact_id or None,
        "validity": "stale_review_required" if review_required else "current",
        "review_task_required": review_required,
        "review_reasons": sorted(set(review_reasons)),
        "blockers": blockers,
        "historical_reasoning_mutated": False,
        "publication_change_authorized": False,
    }
