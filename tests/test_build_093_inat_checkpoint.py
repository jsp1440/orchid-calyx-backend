import harvesters.inat as inat


def test_inat_resume_and_checkpoint_and_dbwrite(monkeypatch):
    saved = []
    monkeypatch.setattr(inat, "get_state", lambda k: {"last_offset": 500})

    batches = [([{"x": 1}], 600), ([], None)]
    monkeypatch.setattr(inat, "fetch_batch",
                        lambda cursor, per_page=200: batches.pop(0))

    writes = []
    monkeypatch.setattr(inat, "insert_images",
                        lambda recs: writes.append(recs) or 1)
    monkeypatch.setattr(
        inat, "save_state",
        lambda k, last_offset=None, increment_total=0: saved.append(
            (k, last_offset, increment_total)))

    result = inat.harvest_all(limit=5)

    assert writes  # DB write function invoked
    assert saved  # checkpoint updated
    assert saved[0][1] == 600  # advanced from resume base (500) to new cursor
    assert result["images"] == 1
