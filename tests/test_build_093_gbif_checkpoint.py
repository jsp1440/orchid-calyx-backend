import harvesters.gbif_api as gbif


class FakeCursor:
    def __init__(self, store):
        self.store = store
        self._result = None

    def execute(self, sql, params=None):
        norm = " ".join(sql.split())
        self.store["sql"].append(norm)
        if "SELECT last_offset, total_inserted" in norm:
            self._result = self.store.get("state_row")
        elif "information_schema" in norm or "SELECT EXISTS" in norm:
            self._result = (True,)

    def fetchone(self):
        return self._result

    def fetchall(self):
        return []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeConn:
    def __init__(self, store):
        self.store = store

    def cursor(self):
        return FakeCursor(self.store)

    def commit(self):
        self.store["commits"] += 1

    def close(self):
        pass


def _install(monkeypatch, state_row=None):
    store = {"sql": [], "commits": 0, "state_row": state_row}
    monkeypatch.setattr(gbif, "get_conn", lambda: FakeConn(store))
    return store


def test_gbif_resumes_from_saved_offset(monkeypatch):
    store = _install(monkeypatch, state_row=(1000, 50))
    offsets = []

    def fake_fetch(session, family_key, offset, limit):
        offsets.append(offset)
        return ([], True)

    monkeypatch.setattr(gbif, "fetch_gbif_page", fake_fetch)
    gbif.run(family_key=7689)

    assert offsets[0] == 1000  # resumed from checkpointed offset
    assert any("oc_harvest_state" in s and "INSERT INTO" in s
               for s in store["sql"])  # checkpoint UPSERT written


def test_gbif_db_writes_and_checkpoint_update(monkeypatch):
    store = _install(monkeypatch, state_row=None)  # fresh -> offset 0
    pages = [([{"key": 1}], False), ([], True)]
    monkeypatch.setattr(gbif, "fetch_gbif_page",
                        lambda s, fk, o, l: pages.pop(0))
    occ, img = [], []
    monkeypatch.setattr(gbif, "insert_occurrences_if_possible",
                        lambda conn, items: occ.append(items) or 1)
    monkeypatch.setattr(gbif, "insert_images_if_possible",
                        lambda conn, items: img.append(items) or 1)

    result = gbif.run()

    assert occ and img  # DB write functions invoked
    assert result["occurrences_added"] == 1
    assert result["images_added"] == 1
    assert result["next_offset"] >= 500  # cursor advanced + saved
