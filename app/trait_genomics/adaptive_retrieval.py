from __future__ import annotations

from typing import Any

from .molecular_harvester import (
    EUROPE_PMC_SEARCH_BASE,
    MOLECULAR_QUERY,
    EuropePMCClient,
)


class AdaptiveEuropePMCClient(EuropePMCClient):
    """Bounded adaptive retrieval without weakening downstream evidence gates.

    Retrieval broadens only when earlier queries do not fill the requested page.
    Candidate acceptance remains entirely in ``EuropePMCMolecularHarvester`` and
    still requires a gene/protein annotation, controlled trait term, and explicit
    relation in the same abstract sentence.
    """

    def __init__(self, *, timeout: int = 30) -> None:
        super().__init__(timeout=timeout)
        self._search_diagnostics: list[dict[str, Any]] = []

    @staticmethod
    def _article_key(article: dict[str, Any]) -> str:
        for field in ("pmcid", "pmid", "doi", "id", "extId"):
            value = str(article.get(field) or "").strip()
            if value:
                return f"{field}:{value.casefold()}"
        title = str(article.get("title") or "").strip()
        return f"title:{title.casefold()}"

    @staticmethod
    def _strategies(scientific_name: str) -> list[tuple[str, str]]:
        cleaned = " ".join((scientific_name or "").split())
        parts = cleaned.split()
        strategies = [
            (
                "exact_taxon_molecular",
                f'"{cleaned}" AND {MOLECULAR_QUERY}',
            )
        ]
        if len(parts) >= 2:
            strategies.append(
                (
                    "tokenized_taxon_molecular",
                    f'"{parts[0]}" AND "{parts[1]}" AND {MOLECULAR_QUERY}',
                )
            )
        strategies.append(("exact_taxon_any", f'"{cleaned}"'))
        return strategies

    def _search_query(self, query: str, *, page_size: int) -> list[dict[str, Any]]:
        payload = self._get_json(
            EUROPE_PMC_SEARCH_BASE,
            {
                "query": query,
                "format": "json",
                "resultType": "core",
                "pageSize": page_size,
            },
        )
        return list((payload or {}).get("resultList", {}).get("result", []) or [])

    def search(self, scientific_name: str, *, page_size: int) -> list[dict[str, Any]]:
        if page_size < 1 or page_size > 100:
            raise ValueError("page_size must be between 1 and 100")

        self._search_diagnostics = []
        accumulated: dict[str, dict[str, Any]] = {}
        for strategy, query in self._strategies(scientific_name):
            if len(accumulated) >= page_size:
                break
            remaining = page_size - len(accumulated)
            articles = self._search_query(query, page_size=remaining)
            added = 0
            article_ids: list[str] = []
            for raw in articles:
                article = dict(raw)
                key = self._article_key(article)
                article_ids.append(key)
                if key in accumulated:
                    continue
                article["_calyx_retrieval_strategy"] = strategy
                article["_calyx_retrieval_query"] = query
                accumulated[key] = article
                added += 1
                if len(accumulated) >= page_size:
                    break
            self._search_diagnostics.append(
                {
                    "strategy": strategy,
                    "query": query,
                    "returned": len(articles),
                    "added_unique": added,
                    "article_ids": article_ids,
                }
            )

        return list(accumulated.values())[:page_size]

    def retrieval_diagnostics(self) -> dict[str, Any]:
        return {
            "adaptive_retrieval": True,
            "queries_executed": len(self._search_diagnostics),
            "strategies": list(self._search_diagnostics),
            "policy": (
                "Retrieval may broaden from exact taxon+molecular terms to tokenized taxon+molecular "
                "terms and finally exact taxon-only retrieval. Downstream molecular evidence gates are "
                "unchanged and all candidates remain review-only."
            ),
        }
