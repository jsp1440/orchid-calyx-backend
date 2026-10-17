"""Synthetic registry responses for native-discovery tests.

Shapes follow the public Crossref, OpenAlex and Europe PMC JSON contracts.
DOIs use Crossref's test prefix 10.5555; titles are fixtures, not real papers.
"""

CROSSREF_PAGE = {
    "status": "ok",
    "message": {
        "items": [
            {
                "DOI": "10.5555/OC-FIXTURE-LEPANTHES",
                "title": [
                    "<i>Lepanthes fixtura</i> (Orchidaceae: Pleurothallidinae), a new species from Ecuador"
                ],
                "author": [
                    {
                        "given": "Ana",
                        "family": "Fixture",
                        "affiliation": [{"name": "Herbario Fixture"}],
                    },
                    {"given": "Luis", "family": "Example"},
                ],
                "container-title": ["Fixture Journal of Botany"],
                "publisher": "Fixture Press",
                "published": {"date-parts": [[2026, 10, 2]]},
                "abstract": "<jats:p>Lepanthes fixtura sp. nov. is described and illustrated from cloud forest.</jats:p>",
                "URL": "https://doi.org/10.5555/oc-fixture-lepanthes",
                "type": "journal-article",
                "subject": ["Plant Science"],
            },
            {
                "DOI": "10.5555/oc-fixture-pollination",
                "title": [
                    "Herbarium flowers reveal long-term decline in orchid pollination"
                ],
                "author": [{"given": "Kim", "family": "Sample"}],
                "container-title": ["Fixture Ecology Letters"],
                "published": {"date-parts": [[2026, 9, 20]]},
                "abstract": "Preserved herbarium specimens of orchids show declining pollinia removal over a century.",
                "URL": "https://doi.org/10.5555/oc-fixture-pollination",
                "type": "journal-article",
            },
            {
                "DOI": "10.5555/oc-fixture-wheat",
                "title": ["Nitrogen response of winter wheat cultivars"],
                "published": {"date-parts": [[2026, 9, 1]]},
                "type": "journal-article",
            },
            {
                "DOI": "10.5555/oc-fixture-old",
                "title": ["A revision of Orchidaceae in a fixture archipelago"],
                "published": {"date-parts": [[1998]]},
                "type": "journal-article",
            },
        ]
    },
}

OPENALEX_PAGE = {
    "results": [
        {
            "id": "https://openalex.org/W999000001",
            "doi": "https://doi.org/10.5555/oc-fixture-pollination",
            "display_name": "Herbarium flowers reveal long-term decline in orchid pollination",
            "publication_date": "2026-09-20",
            "type": "article",
            "authorships": [
                {
                    "author": {"display_name": "Kim Sample"},
                    "institutions": [{"display_name": "Fixture University"}],
                }
            ],
            "primary_location": {
                "landing_page_url": "https://fixture.example/pollination",
                "source": {
                    "display_name": "Fixture Ecology Letters",
                    "host_organization_name": "Fixture Press",
                },
            },
            "abstract_inverted_index": {
                "Preserved": [0],
                "orchid": [1],
                "specimens": [2],
                "pollinators": [3],
            },
            "keywords": [{"display_name": "Pollination"}],
        }
    ]
}

EUROPEPMC_PAGE = {
    "resultList": {
        "result": [
            {
                "id": "PPR000001",
                "source": "PPR",
                "doi": "10.5555/oc-fixture-mycorrhiza",
                "title": "Mycorrhizal partners of a terrestrial orchid across a fixture gradient",
                "authorList": {"author": [{"fullName": "Doe J"}]},
                "firstPublicationDate": "2026-10-05",
                "abstractText": "Fungal symbionts of Orchidaceae were sequenced.",
            }
        ]
    }
}


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class FakeHttp:
    """Routes by host and records every requested URL for cost assertions."""

    def __init__(self, pages=None, failures=None):
        self.pages = pages or {
            "api.crossref.org": CROSSREF_PAGE,
            "api.openalex.org": OPENALEX_PAGE,
            "www.ebi.ac.uk": EUROPEPMC_PAGE,
        }
        self.failures = failures or {}
        self.urls: list[str] = []

    def __call__(self, url, **kwargs):
        self.urls.append(url)
        for host, status in self.failures.items():
            if host in url:
                return FakeResponse({}, status)
        for host, page in self.pages.items():
            if host in url:
                return FakeResponse(page)
        return FakeResponse({}, 404)
