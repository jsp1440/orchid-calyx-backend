from harvesters import gbif_global_api


class FakeConnection:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def test_gbif_checkpoints_each_successful_page(monkeypatch):
    conn = FakeConnection()
    monkeypatch.setattr(gbif_global_api.gbif_api, "get_conn", lambda: conn)
    monkeypatch.setattr(gbif_global_api, "_load_state", lambda conn: {"offset": 0, "total": 0})

    pages = iter(
        [
            ([{"key": 1}, {"key": 2}], False),
            ([{"key": 3}], True),
        ]
    )
    monkeypatch.setattr(
        gbif_global_api,
        "_fetch_page",
        lambda session, *, family_key, offset, limit: next(pages),
    )
    monkeypatch.setattr(
        gbif_global_api.gbif_api,
        "insert_occurrences_if_possible",
        lambda conn, items: len(items),
    )
    monkeypatch.setattr(
        gbif_global_api.gbif_api,
        "insert_images_if_possible",
        lambda conn, items: 1 if len(items) == 2 else 0,
    )
    checkpoints = []
    monkeypatch.setattr(
        gbif_global_api,
        "_save_state",
        lambda conn, *, offset, total_delta: checkpoints.append((offset, total_delta)),
    )
    monkeypatch.setattr(gbif_global_api.time, "sleep", lambda _: None)

    result = gbif_global_api.run(max_pages=10, max_runtime_seconds=120)

    assert checkpoints == [(2, 3), (3, 1)]
    assert result["next_offset"] == 3
    assert result["records_examined"] == 3
    assert result["occurrences_added"] == 3
    assert result["images_added"] == 1
    assert conn.closed is True
