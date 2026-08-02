from runtime.world_plants_ingest import (
    build_snapshot,
    compare_releases,
    parse_world_orchids_release,
    promotion_plan,
)


def _release(*rows: str) -> bytes:
    header = (
        "Taxon|Number|Name|Literature|TrivialName|Distribution|Synonyms|Status|"
        "Remarks|ConservationStatus|Photo|Orientation|Author"
    )
    return ("\n".join((header, *rows)) + "\n").encode("latin-1")


def _row(code: str, name: str, number: str = "", photo: str = "") -> str:
    fields = [
        code,
        number,
        name,
        "literature",
        "",
        "distribution",
        "= old name",
        "",
        "",
        "",
        photo,
        "landscape" if photo else "",
        "author" if photo else "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
    ]
    assert len(fields) == 22
    return "|".join(fields)


def test_parses_actual_22_field_shape_and_preserves_four_photo_slots():
    payload = _release(_row("S", "Cattleya labiata Lindl.", "12.3", "image.jpg"))
    result = parse_world_orchids_release(payload)

    assert result.summary() == {
        "rows": 1,
        "issues": 0,
        "source_encoding": "utf-8",
        "rank_counts": {"S": 1},
        "photo_references": 1,
    }
    row = result.rows[0]
    assert row.values["world_plants_number"] == "12.3"
    assert row.values["synonyms_raw"] == "= old name"
    assert row.photos()[0]["photo"] == "image.jpg"


def test_invalid_width_is_reported_and_not_loaded():
    payload = _release("S||Cattleya labiata")
    result = parse_world_orchids_release(payload)

    assert not result.rows
    assert result.issues[0]["reason"] == "unexpected_row_width"


def test_release_delta_blocks_duplicates_and_requires_owner_approval():
    old = parse_world_orchids_release(_release(_row("S", "Old species"))).rows
    new = parse_world_orchids_release(
        _release(
            _row("S", "New species"),
            _row("S", "New species"),
        )
    ).rows
    delta = compare_releases(old, new)
    snapshot = build_snapshot(
        _release(_row("S", "New species")),
        version_label="26-08",
        acquired_at="2026-08-02",
        filename="WorldOrchids 26-08.csv",
    )
    plan = promotion_plan(snapshot, delta)

    assert delta.added == (("S", "New species"),)
    assert delta.removed == (("S", "Old species"),)
    assert delta.duplicate_keys_new == (("S", "New species"),)
    assert plan["automatic_promotion"] is False
    assert plan["delta"]["owner_approval_required"] is True
    assert plan["delta"]["promotion_allowed"] is False
