from __future__ import annotations

from app.trait_genomics.adaptive_retrieval import AdaptiveEuropePMCClient


class FakeAdaptiveClient(AdaptiveEuropePMCClient):
    def __init__(self, responses):
        super().__init__()
        self.responses = responses
        self.calls = []

    def _get_json(self, base_url, params):
        query = params["query"]
        self.calls.append((base_url, dict(params)))
        rows = self.responses.get(query, [])
        return {"resultList": {"result": rows}}


def article(pmid: str, title: str = "Orchid paper"):
    return {"pmid": pmid, "title": title, "abstractText": "Abstract"}


def test_adaptive_retrieval_falls_back_when_exact_molecular_query_is_empty():
    probe = FakeAdaptiveClient({})
    strategies = probe._strategies("Dendrobium cuthbertsonii")
    exact_name, exact_query = strategies[0]
    token_name, token_query = strategies[1]
    any_name, any_query = strategies[2]
    assert exact_name == "exact_taxon_molecular"
    assert token_name == "tokenized_taxon_molecular"
    assert any_name == "exact_taxon_any"

    client = FakeAdaptiveClient(
        {
            exact_query: [],
            token_query: [article("1")],
            any_query: [article("2")],
        }
    )
    rows = client.search("Dendrobium cuthbertsonii", page_size=2)

    assert [row["pmid"] for row in rows] == ["1", "2"]
    assert rows[0]["_calyx_retrieval_strategy"] == "tokenized_taxon_molecular"
    assert rows[1]["_calyx_retrieval_strategy"] == "exact_taxon_any"
    diagnostics = client.retrieval_diagnostics()
    assert diagnostics["adaptive_retrieval"] is True
    assert diagnostics["queries_executed"] == 3
    assert [item["strategy"] for item in diagnostics["strategies"]] == [
        "exact_taxon_molecular",
        "tokenized_taxon_molecular",
        "exact_taxon_any",
    ]


def test_adaptive_retrieval_stops_when_requested_page_is_full():
    probe = FakeAdaptiveClient({})
    _, exact_query = probe._strategies("Dendrobium cuthbertsonii")[0]
    client = FakeAdaptiveClient({exact_query: [article("1"), article("2")]})

    rows = client.search("Dendrobium cuthbertsonii", page_size=2)

    assert len(rows) == 2
    assert len(client.calls) == 1
    assert client.retrieval_diagnostics()["queries_executed"] == 1


def test_adaptive_retrieval_deduplicates_articles_across_strategies():
    probe = FakeAdaptiveClient({})
    strategies = probe._strategies("Dendrobium cuthbertsonii")
    exact_query = strategies[0][1]
    token_query = strategies[1][1]
    any_query = strategies[2][1]
    duplicate = article("1")
    client = FakeAdaptiveClient(
        {
            exact_query: [duplicate],
            token_query: [duplicate],
            any_query: [article("2")],
        }
    )

    rows = client.search("Dendrobium cuthbertsonii", page_size=2)

    assert [row["pmid"] for row in rows] == ["1", "2"]
    assert rows[0]["_calyx_retrieval_strategy"] == "exact_taxon_molecular"
    diagnostics = client.retrieval_diagnostics()
    assert diagnostics["strategies"][1]["added_unique"] == 0


def test_adaptive_retrieval_remains_bounded_to_page_size():
    probe = FakeAdaptiveClient({})
    exact_query = probe._strategies("Dendrobium cuthbertsonii")[0][1]
    client = FakeAdaptiveClient(
        {exact_query: [article("1"), article("2"), article("3")]}
    )

    rows = client.search("Dendrobium cuthbertsonii", page_size=2)

    assert [row["pmid"] for row in rows] == ["1", "2"]
